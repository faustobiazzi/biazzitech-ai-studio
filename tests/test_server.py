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
        # app instalável (PWA): manifesto e service worker na raiz, ícones PNG de verdade
        st, h, raw = self.call("/manifest.webmanifest")
        self.assertEqual(st, 200)
        man = json.loads(raw)
        self.assertEqual(man["display"], "standalone")
        self.assertTrue(any(i.get("purpose") == "maskable" for i in man["icons"]))
        st, h, raw = self.call("/sw.js")
        self.assertEqual(st, 200)
        self.assertIn("javascript", h["Content-Type"])
        for icon in man["icons"]:
            st, h, raw = self.call(icon["src"])
            self.assertEqual((st, h["Content-Type"], raw[:8]), (200, "image/png", b"\x89PNG\r\n\x1a\n"))
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

    def test_admin_restart_cancel_and_smart_assist(self):
        called = []
        orig_restart = studio_server.schedule_restart
        orig_ask = studio_server.prompt_assist._ask
        studio_server.schedule_restart = lambda delay=0.35: called.append(delay)
        try:
            # Sem usuários (admin local): restart agenda reinício e cancel responde 200
            st, _, raw = self.call("/api/access/restart", {})
            self.assertEqual(st, 200)
            self.assertTrue(json.loads(raw)["restarting"])
            self.assertEqual(len(called), 1)
            self.assertEqual(self.call("/api/image/cancel", {})[0], 200)

            # Com usuários e auth_local=True: usuário comum (só chat) não pode reiniciar (403)
            access.add_user("admin1", "segredo1", ["chat", "imagens", "admin"])
            _, _, tok = access.add_user("comum", "segredo2", ["chat"])
            access.set_config(auth_local=True)
            st, _, _ = self.call("/api/access/restart", {}, {"Authorization": f"Bearer {tok}"})
            self.assertEqual(st, 403)

            # mode='auto' no /api/prompt-assist: layout composto gera 1 prompt por quadro; sem quadros gera 1 splash
            access.set_config(auth_local=False)
            studio_server.prompt_assist._ask = lambda sys_p, usr, imgs, mod: (
                ('{"panels": [{"prompt": "p1"}, {"prompt": "p2"}, {"prompt": "p3"}, {"prompt": "p4"}]}',
                 {"provider": "p", "model": "m"})
                if sys_p is studio_server.prompt_assist.PLAN_SYSTEM else
                ('{"prompt": "splash hero", "negative": "text", "aspect": "16:9", "explanation": "ok"}',
                 {"provider": "p", "model": "m"})
            )
            st, _, raw = self.call("/api/prompt-assist", {"mode": "auto", "instruction": "luta", "layout": "grade_4"})
            d1 = json.loads(raw)
            self.assertEqual((st, d1["kind"], len(d1["panels"])), (200, "panels", 4))

            st, _, raw = self.call("/api/prompt-assist", {"mode": "auto", "instruction": "herói no penhasco", "layout": ""})
            d2 = json.loads(raw)
            self.assertEqual((st, d2["kind"], d2["prompt"]), (200, "single", "splash hero"))
        finally:
            studio_server.schedule_restart = orig_restart
            studio_server.prompt_assist._ask = orig_ask

    def test_gallery_persistence_sidecar_json_and_no_orphans(self):
        import os
        import struct
        import zlib
        import base64

        def make_png_bytes(w, h, color=b"\x10\x20\x30\xff"):
            raw = b"".join(b"\x00" + color * w for _ in range(h))
            def chunk(t, d):
                return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
            return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                    + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))

        out_dir = studio_server.get_output_images_dir()
        # 1) Imagem antiga sem .json (ex.: studio_animagine_1795738767.jpg) + um .json órfão sem imagem
        legacy_img = os.path.join(out_dir, "studio_animagine_1795738767.png")
        with open(legacy_img, "wb") as f:
            f.write(make_png_bytes(12, 8))
        orphan_json = os.path.join(out_dir, "fantasma_sem_imagem.json")
        with open(orphan_json, "w", encoding="utf-8") as f:
            json.dump({"file_name": "fantasma_sem_imagem.png"}, f)

        st, _, raw = self.call("/api/images")
        self.assertEqual(st, 200)
        imgs = json.loads(raw)["images"]
        self.assertEqual([i["file_name"] for i in imgs], ["studio_animagine_1795738767.png"])
        self.assertEqual((imgs[0]["width"], imgs[0]["height"]), (12, 8))
        self.assertEqual(imgs[0]["model"], "community/vendouple/animagine")
        # O .json órfão sumiu e a imagem antiga ganhou seu .json anexo de mesmo nome
        self.assertFalse(os.path.exists(orphan_json))
        legacy_json = os.path.join(out_dir, "studio_animagine_1795738767.json")
        self.assertTrue(os.path.isfile(legacy_json))

        # 2) Nova imagem salva via /api/image/upload cria imagem + .json com dados de criação
        durl = "data:image/png;base64," + base64.b64encode(make_png_bytes(16, 10)).decode()
        st, _, raw = self.call("/api/image/upload", {"data_url": durl, "label": "quadro_teste", "prompt": "90s manga hero"})
        self.assertEqual(st, 200)
        up = json.loads(raw)
        up_img = os.path.join(out_dir, up["file_name"])
        up_json = os.path.splitext(up_img)[0] + ".json"
        self.assertTrue(os.path.isfile(up_img) and os.path.isfile(up_json))
        with open(up_json, encoding="utf-8") as f:
            meta1 = json.load(f)
        self.assertEqual((meta1["prompt"], meta1["width"], meta1["height"], meta1["modified"]), ("90s manga hero", 16, 10, False))

        # 3) Se a imagem for alterada no disco, o .json anexo é atualizado (dimensões/hash/modified) preservando o prompt
        with open(up_img, "wb") as f:
            f.write(make_png_bytes(24, 18, b"\xaa\xbb\xcc\xff"))
        st, _, raw = self.call("/api/images")
        self.assertEqual(st, 200)
        with open(up_json, encoding="utf-8") as f:
            meta2 = json.load(f)
        self.assertEqual((meta2["prompt"], meta2["width"], meta2["height"], meta2["modified"]), ("90s manga hero", 24, 18, True))
        self.assertNotEqual(meta1["sha256"], meta2["sha256"])

        # 4) Se a imagem for excluída via /api/image/delete, o .json também é removido
        st, _, _ = self.call("/api/image/delete", {"name": up["file_name"]})
        self.assertEqual(st, 200)
        self.assertFalse(os.path.exists(up_img))
        self.assertFalse(os.path.exists(up_json))

        # 5) Se a imagem for apagada manualmente no disco, a próxima sincronização apaga o .json órfão
        os.remove(legacy_img)
        st, _, raw = self.call("/api/images")
        self.assertEqual(json.loads(raw)["images"], [])
        self.assertFalse(os.path.exists(legacy_json))


if __name__ == "__main__":
    unittest.main()
