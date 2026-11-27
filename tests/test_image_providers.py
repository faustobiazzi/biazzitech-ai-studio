import base64
import json
import unittest
from unittest import mock

from _env import write_env, clear_data

import image_providers
import provider_router as router

FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


class NewImageProvidersTests(unittest.TestCase):
    def setUp(self):
        clear_data()
        write_env(
            GEMINI_API_KEY="k-gem",
            HF_TOKEN="k-hf",
            OPENAI_API_KEY="k-oai",
            TOGETHER_API_KEY="k-tog",
            FAL_KEY="id12345:secret67890",
            STABILITY_API_KEY="k-stab",
        )
        router.load_env()
        image_providers._HF_MAP_CACHE.clear()

    def test_all_new_providers_registered(self):
        for pid in ("gemini_image", "huggingface", "openai_image", "together", "fal", "stability"):
            self.assertTrue(image_providers.is_image_provider(pid), pid)

    def test_huggingface_routes_via_inference_provider_and_falls_back_on_410(self):
        mapping = [("hf-inference", "/hf-inference/models/old/model", "old/model"),
                   ("fal-ai", "/fal-ai/fal-ai/flux/schnell", "fal-ai/flux/schnell")]
        with mock.patch.object(image_providers, "_hf_discover_routes", return_value=mapping), \
             mock.patch.object(image_providers, "_http_raw", side_effect=image_providers.ImageError("Erro 410 do provedor: deprecated")), \
             mock.patch.object(image_providers, "_http", return_value=(200, {"images": [{"url": "https://x/img.png"}]})), \
             mock.patch.object(image_providers, "_download", return_value=FAKE_PNG):
            out = image_providers.generate("huggingface", {"prompt": "a cat", "aspect": "16:9"})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][1], ".png")

    def test_fal_requires_id_colon_secret_and_shared_menu_availability(self):
        ok, msg = router.set_key("fal", "apenas_metade_sem_dois_pontos_12345", validate=False)
        self.assertFalse(ok)
        self.assertIn("ID:SEGREDO", msg)

        write_env(GEMINI_API_KEY="k-gem", FAL_KEY="sem_dois_pontos_35_caracteres_12345")
        router.load_env()
        self.assertIn("ID:SEGREDO", router.unavailable_reason("fal") or "")
        av = router.model_availability(["gemini_image", "openai_image"])
        self.assertTrue(av["gemini_image"]["show"])
        self.assertEqual(av["gemini_image"]["provider"], "gemini")
        self.assertFalse(av["openai_image"]["show"])
        self.assertEqual(av["openai_image"]["provider"], "openai")

    def test_gemini_image_supports_reference(self):
        b64_png = base64.b64encode(FAKE_PNG).decode("ascii")
        fake_resp = {
            "candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": b64_png}}]}}]
        }
        with mock.patch.object(image_providers, "_http", return_value=(200, fake_resp)) as m_http:
            out = image_providers.generate("gemini_image", {"prompt": "edit this", "reference": FAKE_PNG, "aspect": "1:1"})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][1], ".png")
        sent_parts = m_http.call_args[0][3]["contents"][0]["parts"]
        self.assertEqual(len(sent_parts), 2)
        self.assertIn("inlineData", sent_parts[0])

    def test_openai_together_fal_stability(self):
        b64_png = base64.b64encode(FAKE_PNG).decode("ascii")
        with mock.patch.object(image_providers, "_http", return_value=(200, {"data": [{"b64_json": b64_png}]})):
            self.assertEqual(image_providers.generate("openai_image", {"prompt": "p"})[0][1], ".png")
            self.assertEqual(image_providers.generate("together", {"prompt": "p"})[0][1], ".png")

        with mock.patch.object(image_providers, "_http", return_value=(200, {"images": [{"url": "https://x/img.png"}]})), \
             mock.patch.object(image_providers, "_download", return_value=FAKE_PNG):
            self.assertEqual(image_providers.generate("fal", {"prompt": "p"})[0][1], ".png")

        with mock.patch.object(image_providers, "_http_raw", return_value=(200, FAKE_PNG)):
            self.assertEqual(image_providers.generate("stability", {"prompt": "p"})[0][1], ".png")


if __name__ == "__main__":
    unittest.main()
