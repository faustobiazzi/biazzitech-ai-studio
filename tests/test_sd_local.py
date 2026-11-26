"""Stable Diffusion local: conversa com um sd-server FALSO (mesma API /sdapi/v1 do stable-diffusion.cpp)."""
import base64
import json
import os
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from _env import DATA, TMP, write_env, clear_data

import characters
import image_providers
import provider_router as router
import sd_local

PNG = base64.b64decode("iVBORw0KGfAAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==".replace("KGfA", "KGgo"))


class FakeSD(BaseHTTPRequestHandler):
    requests = []
    loras = [{"name": "lcm-lora-sdv1-5", "path": "lcm-lora-sdv1-5.safetensors"},
             {"name": "pixel-art", "path": "estilos/pixel-art.safetensors"},
             {"name": "kael", "path": "personagens/kael.safetensors"}]

    def _json(self, obj):
        raw = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/sdapi/v1/options":
            return self._json({"samples_format": "png", "sd_model_checkpoint": "x"})
        if self.path == "/sdapi/v1/loras":
            return self._json(self.loras)
        if self.path == "/sdapi/v1/samplers":
            return self._json([{"name": n} for n in ("euler", "euler_a", "lcm", "dpm++2m")])
        self.send_error(404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeSD.requests.append((self.path, body))
        self._json({"images": [base64.b64encode(PNG).decode()], "parameters": body, "info": ""})

    def log_message(self, *a):
        pass


class SDLocalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeSD)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        clear_data()
        FakeSD.requests.clear()
        write_env(SDLOCAL_ENABLED="1", SDLOCAL_URL=self.url)
        router.load_env()

    def tearDown(self):
        write_env()
        router.load_env()

    def test_fast_mode_uses_lcm_and_requested_loras(self):
        imgs = image_providers.generate("sdlocal", {"prompt": "knight", "aspect": "3:4",
                                                    "loras": [{"name": "pixel-art", "weight": 0.7}]})
        self.assertEqual(imgs[0][1], ".png")
        path, body = FakeSD.requests[-1]
        self.assertEqual(path, "/sdapi/v1/txt2img")
        self.assertEqual((body["width"], body["height"]), (480, 640))  # SD 1.5
        self.assertEqual(body["sampler_name"], "lcm")
        self.assertEqual(body["steps"], 6)
        self.assertIn({"path": "estilos/pixel-art.safetensors", "multiplier": 0.7}, body["lora"])
        self.assertIn({"path": "lcm-lora-sdv1-5.safetensors", "multiplier": 1.0}, body["lora"])

    def test_quality_mode_and_reference_image(self):
        sd_local.generate({"prompt": "castle", "fast": False, "reference": PNG, "strength": 0.4})
        path, body = FakeSD.requests[-1]
        self.assertEqual(path, "/sdapi/v1/img2img")
        self.assertEqual(body["sampler_name"], "euler_a")
        self.assertEqual(body["steps"], 22)
        self.assertEqual(body["lora"], [])
        self.assertAlmostEqual(body["denoising_strength"], 0.4)
        self.assertEqual(base64.b64decode(body["init_images"][0]), PNG)

    def test_missing_lora_is_reported(self):
        with self.assertRaises(image_providers.ImageError) as ctx:
            image_providers.generate("sdlocal", {"prompt": "x", "loras": [{"name": "nao-existe"}]})
        self.assertIn("nao-existe", str(ctx.exception))

    def test_sdxl_sizes_and_family(self):
        self.assertEqual(sd_local.family("sd_xl_base_1.0.safetensors"), "sdxl")
        self.assertEqual(sd_local.family("stable-diffusion-v1-5-pruned-emaonly-Q8_0.gguf"), "sd15")
        sd_local.generate({"prompt": "x", "model": "sd_xl_base_1.0.safetensors", "aspect": "16:9", "fast": False})
        body = FakeSD.requests[-1][1]
        self.assertEqual((body["width"], body["height"]), (1344, 768))

    def test_status_and_provider_card(self):
        st = sd_local.status()
        self.assertTrue(st["installed"] and st["enabled"] and st["running"])
        self.assertIsNone(router.unavailable_reason("sdlocal"))
        write_env()
        router.load_env()
        self.assertIn("desativado", router.unavailable_reason("sdlocal"))

    def test_local_files_are_listed(self):
        write_env(SDLOCAL_ENABLED="1", SDLOCAL_DIR=os.path.join(TMP, "sdl"))
        router.load_env()
        for rel in ("models/checkpoints/sd15.gguf", "models/loras/lcm-lora-sdv1-5.safetensors",
                    "models/loras/estilos/pixel.safetensors"):
            p = os.path.join(TMP, "sdl", *rel.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "wb").close()
        st = sd_local.status()
        self.assertEqual([m["file"] for m in st["models"]], ["sd15.gguf"])
        self.assertEqual([l["file"] for l in st["loras"]], ["estilos/pixel.safetensors", "lcm-lora-sdv1-5.safetensors"])
        self.assertFalse(sd_local.installed())  # sem o sd-server.exe
        with self.assertRaises(sd_local.SDError):
            sd_local.ensure_server("sd15.gguf")


class FakeA1111(FakeSD):
    """AUTOMATIC1111/Forge: sem /sdcpp/v1/capabilities, LoRA vai como <lora:...> no prompt, pede senha."""
    def do_GET(self):
        if self.headers.get("Authorization") != "Basic " + base64.b64encode(b"ana:segredo").decode():
            self.send_error(401)
            return
        if self.path == "/sdapi/v1/sd-models":
            return self._json([{"title": "dreamshaper_8.safetensors [abc]", "model_name": "dreamshaper_8"}])
        if self.path == "/sdapi/v1/options":
            return self._json({"sd_model_checkpoint": "dreamshaper_8.safetensors [abc]"})
        if self.path == "/sdapi/v1/loras":
            return self._json([{"name": "pixel-art", "path": "C:/sd/models/Lora/pixel-art.safetensors"}])
        if self.path == "/sdapi/v1/samplers":
            return self._json([{"name": "Euler a"}, {"name": "LCM"}])
        self.send_error(404)


class FakeSdcpp(FakeSD):
    def do_GET(self):
        if self.path == "/sdcpp/v1/capabilities":
            return self._json({"features": ["lora"]})
        if self.path == "/sdapi/v1/sd-models":
            return self._json([{"title": "sd15", "model_name": "sd15"}])
        return super().do_GET()


class RemoteImageServerTest(unittest.TestCase):
    """Stable Diffusion de outro PC cadastrado como provedor personalizado do tipo 'imagens'."""
    @classmethod
    def setUpClass(cls):
        cls.servers = []
        for handler in (FakeA1111, FakeSdcpp):
            s = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            threading.Thread(target=s.serve_forever, daemon=True).start()
            cls.servers.append(s)
        cls.a1111 = f"http://127.0.0.1:{cls.servers[0].server_port}"
        cls.sdcpp = f"http://127.0.0.1:{cls.servers[1].server_port}"

    @classmethod
    def tearDownClass(cls):
        for s in cls.servers:
            s.shutdown()
            s.server_close()

    def setUp(self):
        clear_data()
        FakeSD.requests.clear()
        write_env()
        router.load_env()
        sd_local._styles.clear()

    def test_a1111_with_password_and_prompt_loras(self):
        ok, msg, models = router.test_custom(self.a1111, "ana:segredo", "imagens")
        self.assertTrue(ok, msg)
        self.assertIn("WebUI", msg)
        self.assertEqual(models, ["dreamshaper_8.safetensors [abc]"])
        self.assertFalse(router.test_custom(self.a1111, "ana:errada", "imagens")[0])
        ok, msg, pid = router.save_custom({"label": "SD do Fulano", "base": self.a1111, "key": "ana:segredo",
                                           "uses": "imagens"})
        self.assertTrue(ok, msg)
        # aparece na lista de imagens, não no rodízio de texto
        self.assertIn(pid, router.custom_ids("imagens"))
        self.assertNotIn(pid, router.custom_ids("texto"))
        self.assertNotIn(pid, router.provider_order())
        self.assertIn(pid, [p["id"] for p in router.status()["providers"]])
        info = image_providers.sd_info(pid)
        self.assertEqual(info["style"], "a1111")
        self.assertEqual(info["loras"][0]["name"], "pixel-art")
        image_providers.generate(pid, {"prompt": "knight", "loras": [{"name": "pixel-art", "weight": 0.7}],
                                       "fast": False, "model": "dreamshaper_8.safetensors [abc]"})
        path, body = FakeSD.requests[-1]
        self.assertEqual(path, "/sdapi/v1/txt2img")
        self.assertIn("<lora:pixel-art:0.7>", body["prompt"])
        self.assertNotIn("lora", body)
        self.assertEqual(body["override_settings"]["sd_model_checkpoint"], "dreamshaper_8.safetensors [abc]")

    def test_sdcpp_server_and_both_uses(self):
        ok, msg, pid = router.save_custom({"label": "PC da sala", "base": self.sdcpp + "/v1", "uses": "ambos",
                                           "skip_test": True})
        self.assertTrue(ok, msg)
        self.assertIn(pid, router.custom_ids("imagens"))
        self.assertIn(pid, router.custom_ids("texto"))
        self.assertEqual(sd_local.remote_target(pid)["url"], self.sdcpp)
        image_providers.generate(pid, {"prompt": "castle", "loras": [{"name": "pixel-art"}]})
        body = FakeSD.requests[-1][1]
        self.assertIn({"path": "estilos/pixel-art.safetensors", "multiplier": 0.8}, body["lora"])
        self.assertEqual(body["cfg_scale"], 1.0)  # LCM com uma passada só

    def test_old_custom_providers_stay_text_only(self):
        ok, _, pid = router.save_custom({"label": "Antigo", "base": "localhost:59990", "skip_test": True})
        self.assertEqual(router.PROVIDERS[pid]["uses"], ["texto"])
        self.assertFalse(image_providers.is_image_provider(pid))


class CharacterLoraTest(unittest.TestCase):
    def setUp(self):
        clear_data()

    def test_lora_fields_and_dataset(self):
        img = "data:image/png;base64," + base64.b64encode(PNG).decode()
        c = characters.save_character({"name": "Kael", "look": "silver hair", "lora": "kael", "lora_weight": "0.9",
                                       "trigger": "kael_hero", "new_images": [img, img]})
        self.assertEqual((c["lora"], c["lora_weight"], c["trigger"]), ("kael", 0.9, "kael_hero"))
        with zipfile.ZipFile(characters.dataset_zip(c["id"])) as z:
            names = z.namelist()
            self.assertIn("kael_hero/kael_hero_01.png", names)
            self.assertEqual(z.read("kael_hero/kael_hero_02.txt").decode(), "kael_hero, silver hair")
        empty = characters.save_character({"name": "Sem imagem"})
        with self.assertRaises(characters.CharacterError):
            characters.dataset_zip(empty["id"])


if __name__ == "__main__":
    unittest.main()
