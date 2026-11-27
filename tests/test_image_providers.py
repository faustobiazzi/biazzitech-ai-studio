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
            FAL_KEY="k-fal",
            STABILITY_API_KEY="k-stab",
        )
        router.load_env()

    def test_all_new_providers_registered(self):
        for pid in ("gemini_image", "huggingface", "openai_image", "together", "fal", "stability"):
            self.assertTrue(image_providers.is_image_provider(pid), pid)

    def test_huggingface_generates_png(self):
        with mock.patch.object(image_providers, "_http_raw", return_value=(200, FAKE_PNG)) as m_raw:
            out = image_providers.generate("huggingface", {"prompt": "a cat", "aspect": "16:9"})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][1], ".png")
        url = m_raw.call_args[0][1]
        self.assertIn("FLUX.1-schnell", url)

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
