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
