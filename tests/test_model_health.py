import io
import json
import os
import tempfile
import unittest
import urllib.error
from unittest import mock

from _env import write_env, clear_data

import model_health
import provider_router as router


class ExtractReplacementTests(unittest.TestCase):
    def test_extracts_gemini_deprecation_message(self):
        msg = (
            "This model models/gemini-2.5-flash is no longer available to new users. "
            "Please update your code to use models/gemini-3.8-flash for the latest features "
            "and improvements. We recommend you to use the Interactions API "
            "(https://aistudio.google.com/docs/get-started)."
        )
        self.assertEqual(router.extract_replacement_model(msg, "gemini-2.5-flash"), "gemini-3.8-flash")

    def test_extracts_other_provider_formats(self):
        self.assertEqual(
            router.extract_replacement_model("Model llama3-70b was replaced by llama-3.3-70b-versatile.", "llama3-70b"),
            "llama-3.3-70b-versatile",
        )
        self.assertEqual(
            router.extract_replacement_model("Deprecated. Please migrate to `gpt-5-mini`.", "gpt-4o-mini"),
            "gpt-5-mini",
        )

    def test_ignores_same_model_and_urls(self):
        msg = "models/gemini-2.5-flash not found. See https://aistudio.google.com/docs/get-started."
        self.assertIsNone(router.extract_replacement_model(msg, "gemini-2.5-flash"))


class OpenChatAutoReplacementTests(unittest.TestCase):
    def setUp(self):
        clear_data()
        write_env(GEMINI_API_KEY="k-gem")
        router.load_env()

    def test_open_chat_retries_regex_replacement_on_404(self):
        seen_models = []

        def fake_urlopen(req, timeout=90):
            body = json.loads(req.data.decode("utf-8"))
            m = body["model"]
            seen_models.append(m)
            if m == "gemini-2.5-flash":
                err_body = json.dumps({
                    "error": {
                        "code": 404,
                        "message": "This model models/gemini-2.5-flash is no longer available. Please update your code to use models/gemini-3.8-flash.",
                    }
                }).encode("utf-8")
                raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(err_body))

            class _FakeResp:
                headers = {}

                def read(self):
                    return json.dumps({"choices": [{"message": {"content": "OK"}}]}).encode("utf-8")

                def close(self):
                    pass

            return _FakeResp()

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            resp, info = router.open_chat({"model": "gemini-2.5-flash", "messages": [{"role": "user", "content": "oi"}]}, only="gemini")
            resp.close()

        self.assertEqual(seen_models, ["gemini-2.5-flash", "gemini-3.8-flash"])
        self.assertEqual(info["model"], "gemini-3.8-flash")


class ModelHealthTests(unittest.TestCase):
    def setUp(self):
        clear_data()
        write_env(GEMINI_API_KEY="k-gem")
        router.load_env()

    def test_heal_uses_regex_and_patches_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            router_copy = os.path.join(tmp, "provider_router.py")
            with open(router_copy, "w", encoding="utf-8") as f:
                f.write('"prefer": ["gemini-flash-latest", "gemini-2.5-flash", "flash"],\n')

            fake_providers = {
                "gemini": {
                    "label": "Google Gemini",
                    "base": "https://example.invalid/v1beta/openai",
                    "key_env": "GEMINI_API_KEY",
                    "default_model": "gemini-2.5-flash",
                    "prefer": ["gemini-2.5-flash"],
                }
            }

            def fake_probe(pid, model, timeout=12):
                if model == "gemini-2.5-flash":
                    return {
                        "model": model,
                        "ok": False,
                        "status": 404,
                        "latency_ms": 10,
                        "error": "Please update your code to use models/gemini-3.8-flash",
                        "replacement": "gemini-3.8-flash",
                    }
                return {"model": model, "ok": True, "status": 200, "latency_ms": 10, "error": None, "replacement": None}

            with mock.patch.dict(router.PROVIDERS, fake_providers, clear=True), \
                 mock.patch.object(model_health, "_fetch_catalog", return_value=([], None)), \
                 mock.patch.object(model_health, "probe_model", side_effect=fake_probe):
                actions = model_health.check_and_heal(providers=["gemini"], apply=True, router_path=router_copy)

            self.assertEqual(len(actions), 1)
            self.assertEqual(actions[0]["replacement"], "gemini-3.8-flash")
            self.assertTrue(actions[0]["applied"])
            with open(router_copy, "r", encoding="utf-8") as f:
                self.assertIn('"gemini-3.8-flash"', f.read())

    def test_heal_falls_back_to_cli_when_regex_and_discovery_fail(self):
        fake_providers = {
            "gemini": {
                "label": "Google Gemini",
                "base": "https://example.invalid/v1beta/openai",
                "key_env": "GEMINI_API_KEY",
                "default_model": "gemini-2.5-flash",
                "prefer": ["gemini-2.5-flash"],
            }
        }
        with mock.patch.dict(router.PROVIDERS, fake_providers, clear=True), \
             mock.patch.object(model_health, "_fetch_catalog", return_value=([], None)), \
             mock.patch.object(model_health, "probe_model", return_value={"model": "gemini-2.5-flash", "ok": False, "status": 404, "error": "Not found", "replacement": None}), \
             mock.patch.object(model_health, "_pick_discovery_replacement", return_value=None), \
             mock.patch.object(model_health, "invoke_cli_updater", return_value={"invoked": True, "cli": "claude", "returncode": 0}) as m_cli:
            actions = model_health.check_and_heal(providers=["gemini"], apply=True, use_cli=True)

        self.assertEqual(len(actions), 1)
        self.assertTrue(actions[0]["cli"]["invoked"])
        m_cli.assert_called_once()


if __name__ == "__main__":
    unittest.main()
