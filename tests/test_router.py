import unittest

from _env import write_env, clear_data

import provider_router as router


class RouterTest(unittest.TestCase):
    def setUp(self):
        clear_data()
        write_env()
        router.load_env()

    # ------------------------------------------------------------ nomes de modelo
    def test_normalize_model(self):
        self.assertEqual(router.normalize_model("groq:openai/gpt-oss-120b"), "groq/openai/gpt-oss-120b")
        self.assertEqual(router.normalize_model("deepseek:deepseek-chat"), "deepseek-chat")
        self.assertEqual(router.normalize_model("claude:claude-opus-5-5"), "claude/claude-opus-5-5")
        self.assertEqual(router.normalize_model("gemma4:26b"), "gemma4:26b")  # nome do Ollama fica igual
        self.assertEqual(router.normalize_model("  auto "), "auto")

    def test_native_provider(self):
        cases = {
            "auto": None, "": None, "deepseek-chat": "deepseek", "gemini-flash-latest": "gemini",
            "groq/llama-3.3-70b": "groq", "meta/llama:free": "openrouter", "grok-4": "xai",
            "claude/auto": "anthropic", "claude-opus-5-5": "anthropic", "chatgpt/auto": "openai",
            "gpt-5": "openai", "o3": "openai", "ollama/qwen": "ollama", "ollama_cloud/x": "ollama_cloud",
            "flux": "pollinations",
        }
        for model, prov in cases.items():
            self.assertEqual(router.native_provider(model), prov, model)

    # ------------------------------------------------------------ .env e chaves extras
    def test_env_reload_adds_and_removes_keys(self):
        write_env(GROQ_API_KEY="gsk_teste")
        router.load_env()
        self.assertEqual(router.provider_key("groq"), "gsk_teste")
        write_env()
        router.load_env()
        self.assertEqual(router.provider_key("groq"), "")
        self.assertEqual(router.unavailable_reason("groq"), "sem chave")

    def test_extra_keys_go_to_the_end_unless_requested(self):
        write_env(GROQ_API_KEY="a", GROQ_API_KEY_2="b", GEMINI_API_KEY="c")
        router.load_env()
        order = router.provider_order()
        self.assertIn("groq#2", order)
        bases = router.provider_order(with_instances=False)
        self.assertGreater(order.index("groq#2"), max(order.index(p) for p in bases))
        plan = router._candidate_plan("groq/llama-3.3-70b")
        self.assertEqual(plan[:2], ["groq", "groq#2"])
        self.assertEqual(router.instances_of("groq#2"), ["groq", "groq#2"])

    def test_auth_headers(self):
        self.assertEqual(router.auth_headers("groq", "k")["Authorization"], "Bearer k")
        h = router.auth_headers("anthropic", "k")
        self.assertEqual(h["x-api-key"], "k")
        self.assertIn("anthropic-version", h)
        self.assertEqual(router.auth_headers("retrodiffusion", "k")["X-RD-Token"], "k")
        self.assertTrue(router.auth_headers("scenario", "a:b")["Authorization"].startswith("Basic "))

    def test_images_only_go_to_providers_that_see_them(self):
        with_img = {"messages": [{"role": "user", "content": [
            {"type": "text", "text": "oi"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA"}}]}]}
        self.assertTrue(router.payload_has_images(with_img))
        self.assertFalse(router.payload_has_images({"messages": [{"role": "user", "content": "oi"}]}))
        self.assertTrue(router.accepts_images("gemini"))
        self.assertTrue(router.accepts_images("openrouter"))
        self.assertFalse(router.accepts_images("groq"))
        self.assertFalse(router.accepts_images("deepseek"))
        self.assertTrue(router.VISION_HINT.search("nvidia/nemotron-3.5-super-vl:free"))
        self.assertFalse(router.VISION_HINT.search("openai/gpt-oss-120b:free"))

    # ------------------------------------------------------------ editar / remover provedores padrão
    def test_edit_disable_remove_and_restore_default_provider(self):
        write_env(GROQ_API_KEY="gsk_x", GROQ_API_KEY_2="gsk_y")
        router.load_env()
        ok, _ = router.edit_provider("groq", {"label": "Groq do trabalho", "model": "llama-3.3-70b-versatile"})
        self.assertTrue(ok)
        self.assertEqual(router.PROVIDERS["groq"]["label"], "Groq do trabalho")
        self.assertEqual(router.PROVIDERS["groq#2"]["label"], "Groq #2")  # a extra não herda o nome
        self.assertEqual(router.resolve_models("groq", "auto"), ["llama-3.3-70b-versatile"])
        router.edit_provider("groq", {"disabled": True})
        self.assertEqual(router.unavailable_reason("groq"), "desligado por você")
        router.edit_provider("groq", {"disabled": False, "label": ""})
        self.assertIsNone(router.unavailable_reason("groq"))
        self.assertEqual(router.PROVIDERS["groq"]["label"], "Groq")
        # remover a extra apaga só a chave dela
        self.assertTrue(router.remove_provider("groq#2")[0])
        self.assertNotIn("groq#2", router.PROVIDERS)
        self.assertEqual(router.provider_key("groq"), "gsk_x")
        # remover o padrão: apaga a chave e esconde; restaurar volta (sem a chave)
        self.assertTrue(router.remove_provider("groq")[0])
        self.assertEqual(router.provider_key("groq"), "")
        st = {p["id"]: p for p in router.status()["providers"]}
        self.assertTrue(st["groq"]["hidden"])
        self.assertTrue(router.restore_provider("groq")[0])
        self.assertFalse({p["id"]: p for p in router.status()["providers"]}["groq"]["hidden"])
        self.assertFalse(router.edit_provider("custom_x", {"label": "y"})[0])

    # ------------------------------------------------------------ listas do painel: só o que funciona
    def test_model_lists_only_show_working_providers(self):
        write_env(GROQ_API_KEY="gsk_x", GEMINI_API_KEY="g")
        router.load_env()
        av = router.model_availability(["auto", "groq/llama-3.3-70b", "gemini-flash-latest", "claude/auto", "pixellab"])
        self.assertTrue(av["auto"]["show"] and av["groq/llama-3.3-70b"]["show"])
        self.assertFalse(av["claude/auto"]["show"])   # sem chave
        self.assertFalse(av["pixellab"]["show"])      # gerador de imagem sem chave
        router._record_error("groq", "m", 429, "rate limit")  # espera curta: continua, marcada
        av = router.model_availability(["groq/llama-3.3-70b"])["groq/llama-3.3-70b"]
        self.assertEqual((av["show"], av["waiting"]), (True, True))
        router._record_error("gemini", "m", 401, "invalid key")  # chave recusada: some
        self.assertFalse(router.model_availability(["gemini-flash-latest"])["gemini-flash-latest"]["show"])
        router.edit_provider("groq", {"disabled": True})
        self.assertFalse(router.model_availability(["groq/x"])["groq/x"]["show"])

    # ------------------------------------------------------------ esperas (cooldown)
    def test_parse_duration(self):
        self.assertEqual(router._parse_duration("2m30s"), 150)
        self.assertEqual(router._parse_duration("850ms"), 0.85)
        self.assertEqual(router._parse_duration("12"), 12)
        self.assertIsNone(router._parse_duration("abc"))

    def test_cooldown_rules(self):
        secs, why = router._cooldown_for(429, {"Retry-After": "120"}, "")
        self.assertEqual(secs, 120)
        secs, why = router._cooldown_for(429, {}, "quota exceeded: requests per day")
        self.assertEqual(why, "limite diário atingido")
        self.assertEqual(router._cooldown_for(402, {}, "")[0], 6 * 3600)
        self.assertEqual(router._cooldown_for(401, {}, "")[0], 6 * 3600)
        self.assertEqual(router._cooldown_for(503, {}, "")[0], 30)
        self.assertEqual(router._cooldown_for(400, {}, "")[0], 0)

    def test_error_puts_provider_on_hold_and_reset_clears(self):
        write_env(GROQ_API_KEY="x")
        router.load_env()
        self.assertIsNone(router.unavailable_reason("groq"))
        router._record_error("groq", "m", 402, "sem saldo")
        self.assertIn("402", router.unavailable_reason("groq"))
        router.reset("groq")
        self.assertIsNone(router.unavailable_reason("groq"))

    def test_daily_limit(self):
        write_env(GROQ_API_KEY="x", GROQ_DAILY_LIMIT="1")
        router.load_env()
        router._record_ok("groq", "m", None)
        self.assertIn("limite diário local", router.unavailable_reason("groq"))

    # ------------------------------------------------------------ provedores personalizados
    def test_normalize_base_url(self):
        self.assertEqual(router.normalize_base_url("localhost:11434"), "http://localhost:11434/v1")
        self.assertEqual(router.normalize_base_url("http://h:1/v1/chat/completions"), "http://h:1/v1")
        self.assertEqual(router.normalize_base_url("https://h/openai/"), "https://h/openai")

    def test_custom_provider_position_and_removal(self):
        ok, msg, pid = router.save_custom({"label": "Meu Servidor", "base": "localhost:59998",
                                           "skip_test": True, "position": "inicio"})
        self.assertTrue(ok, msg)
        self.assertEqual(router.provider_order()[0], pid)
        self.assertEqual(router.native_provider(f"{pid}/auto"), pid)
        ok, _, pid2 = router.save_custom({"label": "Outro", "base": "localhost:59997", "skip_test": True,
                                          "position": "fim"})
        bases = router.provider_order(with_instances=False)
        self.assertEqual(bases[-1], pid2)
        for p in (pid, pid2):
            self.assertTrue(router.delete_custom(p)[0])
        self.assertEqual(router.custom_ids(), [])


if __name__ == "__main__":
    unittest.main()
