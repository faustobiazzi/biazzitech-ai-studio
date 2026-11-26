"""Sobe o servidor de verdade numa porta livre (só 127.0.0.1) e testa as rotas sem internet."""
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


class ServerTest(unittest.TestCase):
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

    def call(self, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        h = {"Content-Type": "application/json"}
        h.update(headers or {})
        req = urllib.request.Request(self.base + path, data=data, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def test_health_and_ui(self):
        st, _, raw = self.call("/healthz")
        self.assertEqual(st, 200)
        self.assertEqual(json.loads(raw)["app"], "biazzitech")
        st, h, raw = self.call("/")
        self.assertEqual(st, 200)
        self.assertIn(b"BiazziTech", raw)
        self.assertIn(b'src="/ui/studio.js"', raw)
        for name, ctype in (("studio.js", "javascript"), ("studio.css", "text/css")):
            st, h, raw = self.call("/ui/" + name)
            self.assertEqual(st, 200)
            self.assertIn(ctype, h["Content-Type"])
            self.assertGreater(len(raw), 1000)
        self.assertEqual(self.call("/ui/../provider_router.py")[0], 404)
        self.assertEqual(self.call("/ui/nao_existe.js")[0], 404)

    def test_comic_and_characters_routes(self):
        st, _, raw = self.call("/api/comic/layouts")
        self.assertEqual(st, 200)
        self.assertGreaterEqual(len(json.loads(raw)["layouts"]), 20)
        st, _, raw = self.call("/api/characters", {"action": "save", "name": "Teste", "look": "x"})
        self.assertEqual(st, 200)
        cid = json.loads(raw)["character"]["id"]
        st, _, raw = self.call("/api/characters", {"action": "detect", "text": "o teste chegou"})
        self.assertEqual(json.loads(raw)["ids"], [cid])
        st, _, raw = self.call("/api/characters")
        self.assertEqual(json.loads(raw)["characters"][0]["name"], "Teste")
        self.assertEqual(self.call("/api/characters", {"action": "delete", "id": cid})[0], 200)
        self.assertEqual(self.call("/api/godot/export", {"image": "nao_existe.png", "frame_w": 8, "frame_h": 8})[0], 400)
        self.assertEqual(self.call("/api/godot/download", {"name": "../../users.json"})[0], 404)

    def test_providers_never_expose_full_keys(self):
        write_env(GROQ_API_KEY="gsk_segredo_muito_longo_123456")
        router.load_env()
        st, _, raw = self.call("/api/providers")
        self.assertEqual(st, 200)
        self.assertNotIn(b"gsk_segredo_muito_longo", raw)

    def test_models_list(self):
        st, _, raw = self.call("/v1/models")
        self.assertEqual(st, 200)
        self.assertTrue(any(m["id"] == "auto" for m in json.loads(raw)["data"]))

    def test_other_site_cannot_use_the_api(self):
        evil = {"Origin": "https://site-malicioso.example"}
        st, _, _ = self.call("/api/providers/reset", {}, evil)
        self.assertEqual(st, 403)
        st, _, _ = self.call("/v1/chat/completions", {"model": "auto", "messages": []}, evil)
        self.assertEqual(st, 403)
        st, _, _ = self.call("/api/image", {"prompt": "x"}, {"Origin": "null"})
        self.assertEqual(st, 403)
        # e o navegador não deixa o outro site LER as respostas (sem CORS liberado para ele)
        st, h, _ = self.call("/api/providers", headers=evil)
        self.assertNotIn("Access-Control-Allow-Origin", h)
        st, h, _ = self.call("/api/providers", headers={"Origin": "http://localhost:9090"})
        self.assertEqual(h.get("Access-Control-Allow-Origin"), "http://localhost:9090")
        self.assertEqual(h.get("X-Content-Type-Options"), "nosniff")

    def test_lan_requires_user_and_risk_acceptance(self):
        st, _, raw = self.call("/api/access/network", {"lan": True})
        self.assertEqual(st, 400)
        self.assertTrue(json.loads(raw)["need_user"])
        access.add_user("ana", "segredo1")
        st, _, raw = self.call("/api/access/network", {"lan": True})
        self.assertTrue(json.loads(raw)["need_risk"])
        st, _, raw = self.call("/api/access/network", {"lan": True, "accept_risk": True})
        self.assertEqual(st, 200)
        self.assertIn("SEM HTTPS", json.loads(raw)["message"])
        self.call("/api/access/network", {"lan": False})
        self.assertFalse(access.get_config()["lan"])

    def test_login_flow(self):
        access.add_user("ana", "segredo1")
        st, h, raw = self.call("/api/auth/login", {"user": "ana", "password": "errada"})
        self.assertEqual(st, 401)
        st, h, raw = self.call("/api/auth/login", {"user": "ana", "password": "segredo1"})
        self.assertEqual(st, 200)
        cookie = h.get("Set-Cookie", "")
        self.assertIn("bt_session=", cookie)
        self.assertIn("HttpOnly", cookie)
        st, _, raw = self.call("/api/auth/me", headers={"Cookie": cookie.split(";")[0]})
        self.assertEqual(json.loads(raw)["user"], "ana")


if __name__ == "__main__":
    unittest.main()
