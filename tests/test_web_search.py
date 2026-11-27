"""Busca na internet e lugares perto: decisão do caminho, formatação e integração com o chat (sem internet)."""
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from _env import write_env, clear_data

import access_control as access
import provider_router as router
import studio_server
import web_search


class ClassifyTest(unittest.TestCase):
    def test_routes(self):
        c = web_search.classify
        self.assertEqual(c("onde tem uma padaria aqui perto?"), "places")
        self.assertEqual(c("farmácia aberta perto de mim"), "places")
        self.assertEqual(c("tem algum posto em Barão Geraldo, Campinas? onde fica"), "places")
        self.assertEqual(c("qual a cotação do dólar hoje?"), "web")
        self.assertEqual(c("quem ganhou o jogo ontem?"), "web")
        self.assertEqual(c("me explica o que é um shader"), "chat")
        self.assertEqual(c("escreva um poema sobre o mar"), "chat")
        self.assertEqual(c("func _ready(): print('hoje')"), "chat")
        self.assertEqual(c("qual a cotação do dólar hoje?", preset="gdscript"), "chat")  # código/lore não busca sozinho
        self.assertEqual(c("qual a cotação do dólar hoje?", mode="off"), "chat")
        self.assertEqual(c("me explica o que é um shader", mode="always"), "web")
        self.assertEqual(c("padaria aqui perto", mode="always"), "places")
        # caso duvidoso: só a IA (opcional) decide
        self.assertEqual(c("quem é o presidente da Nintendo?"), "chat")
        self.assertEqual(c("quem é o presidente da Nintendo?", ask=lambda t: "web"), "web")

    def test_place_types(self):
        self.assertEqual(web_search.place_type("tem farmácia aqui?")[0], "Farmácias")
        self.assertEqual(web_search.place_type("um açougue perto")[0], "Açougues")
        self.assertEqual(web_search.place_type("caixa eletrônico 24 horas")[0], "Caixas eletrônicos")
        self.assertIsNone(web_search.place_type("um lugar legal")[0])

    def test_places_without_location_asks_for_it(self):
        res = web_search.places("padaria aqui perto")
        self.assertTrue(res["need_location"])
        self.assertTrue(web_search.places("farmácia perto de mim")["need_location"])

    def test_named_place_wins_over_browser_location(self):
        seen = {}
        orig = (web_search.geocode, web_search._nominatim_near)
        web_search.geocode = lambda name: (-22.82, -47.08, "Barão Geraldo, Campinas")

        def near(word, lat, lon, radius):
            seen["at"] = (lat, lon)
            return [{"lat": lat + 0.001, "lon": lon, "tags": {"name": "Padaria do Barão"}}]
        web_search._nominatim_near = near
        try:
            res = web_search.places("padaria perto de Barão Geraldo, Campinas", lat=-23.55, lon=-46.63)
        finally:
            web_search.geocode, web_search._nominatim_near = orig
        self.assertEqual(seen["at"], (-22.82, -47.08))
        self.assertEqual(res["where"], "Barão Geraldo")
        self.assertEqual(res["items"][0]["name"], "Padaria do Barão")

    def test_format(self):
        res = {"label": "Padarias", "where": "você", "radius": 1200, "accuracy": 900, "need_location": False,
               "items": [{"name": "Padaria Boa", "dist": 270.4, "address": "Rua A, 10", "hours": "Mo-Su 06:00-20:00",
                          "phone": "", "lat": -23.5, "lon": -46.6}]}
        out = web_search.format_places(res)
        self.assertIn("1. Padaria Boa — 270 m", out)
        self.assertIn("openstreetmap.org/?mlat=-23.500000", out)
        self.assertIn("precisão de ~900 m", out)
        out = web_search.format_search({"answer": "Dólar **R$ 5,65** hoje", "provider": "Groq",
                                        "sources": [{"title": "Valor", "url": "https://valor.com"}]})
        self.assertIn("Dólar R$ 5,65 hoje", out)
        self.assertIn("1. Valor — https://valor.com", out)


class WebChatTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), studio_server.StudioHandler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_port}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        clear_data()
        write_env()
        router.load_env()
        access._sessions.clear()
        self.calls = []
        self.orig = (router.chat_completion, web_search.search, web_search.places)
        router.chat_completion = lambda payload, **kw: (self.calls.append("chat") or
            ({"choices": [{"message": {"content": "resposta da IA"}}], "model": "m"}, {"provider": "fake"}))

    def tearDown(self):
        router.chat_completion, web_search.search, web_search.places = self.orig

    def chat(self, text, **extra):
        body = {"content": text, "system": "s", "preset": "free", **extra}
        req = urllib.request.Request(self.base + "/api/chat", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())

    def test_web_question_uses_search_not_chat(self):
        web_search.search = lambda q, h=None: {"answer": "R$ 5,65", "sources": [{"title": "t", "url": "https://x.br"}],
                                               "provider": "Groq"}
        d = self.chat("qual a cotação do dólar hoje?")
        self.assertEqual(d["kind"], "web")
        self.assertIn("R$ 5,65", d["reply"])
        self.assertEqual(self.calls, [])            # a IA de conversa não foi chamada
        d = self.chat("me explica o que é um shader", conversation_id=d["conversation_id"])
        self.assertNotIn("kind", d)
        self.assertEqual(self.calls, ["chat"])

    def test_web_failure_falls_back_to_chat(self):
        def boom(q, h=None):
            raise web_search.WebError("sem buscador")
        web_search.search = boom
        d = self.chat("qual a cotação do dólar hoje?")
        self.assertEqual(d["reply"], "resposta da IA")

    def test_places_with_and_without_location(self):
        got = {}

        def fake_places(text, lat=None, lon=None, accuracy=None):
            got.update(lat=lat, lon=lon)
            if lat is None:
                return {"need_location": True, "label": "Padarias"}
            return {"need_location": False, "label": "Padarias", "where": "você", "radius": 1200, "accuracy": None,
                    "items": [{"name": "Padaria Boa", "dist": 100, "address": "", "hours": "", "phone": "", "lat": 1, "lon": 2}]}
        web_search.places = fake_places
        d = self.chat("onde tem padaria aqui perto?", secure=False)
        self.assertTrue(d["need_location"])
        self.assertIn("HTTPS", d["reply"])
        d = self.chat("onde tem padaria aqui perto?", location={"lat": -23.5, "lon": -46.6, "accuracy": 20}, secure=True)
        self.assertEqual(d["kind"], "places")
        self.assertIn("Padaria Boa", d["reply"])
        self.assertEqual((got["lat"], got["lon"]), (-23.5, -46.6))
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
