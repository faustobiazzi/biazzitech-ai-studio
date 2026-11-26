import io
import json
import os
import subprocess
import sys
import unittest
import zipfile

from _env import ROOT, write_env, clear_data

import doc_extract
import prompt_assist
import provider_router as router


def make_docx(paragraphs):
    xml = ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
           'wordprocessingml/2006/main"><w:body>'
           + "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
           + "</w:body></w:document>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


class DocExtractTest(unittest.TestCase):
    def test_markdown_and_latin1(self):
        self.assertIn("Capítulo", doc_extract.extract("a.md", "# Capítulo 1".encode("utf-8"))[0])
        self.assertIn("ação", doc_extract.extract("a.txt", "ação".encode("latin-1"))[0])

    def test_docx(self):
        text, warn = doc_extract.extract("cena.docx", make_docx(["Primeiro parágrafo", "Segundo"]))
        self.assertIn("Primeiro parágrafo", text)
        self.assertIn("Segundo", text)
        self.assertIsNone(warn)

    def test_unsupported(self):
        with self.assertRaises(doc_extract.ExtractError):
            doc_extract.extract("x.exe", b"MZ")


class PromptAssistTest(unittest.TestCase):
    def setUp(self):
        clear_data()
        write_env()
        router.load_env()

    def test_parse_json_variants(self):
        self.assertEqual(prompt_assist._parse_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(prompt_assist._parse_json('texto antes {"a": [1, 2,],} depois'), {"a": [1, 2]})
        with self.assertRaises(prompt_assist.AssistError):
            prompt_assist._parse_json("sem json")

    def test_pick_model(self):
        self.assertEqual(prompt_assist.pick_model(False, "groq/x"), "groq/x")  # escolha do usuário
        self.assertEqual(prompt_assist.pick_model(True), "auto")  # nenhum provedor com visão
        write_env(GEMINI_API_KEY="x", GROQ_API_KEY="y")
        router.load_env()
        self.assertEqual(prompt_assist.pick_model(True), "gemini-flash-latest")
        write_env(GROQ_API_KEY="y")
        router.load_env()
        self.assertEqual(prompt_assist.pick_model(False), "groq/openai/gpt-oss-120b")

    def test_single_prompt(self):
        seen = {}

        def fake_ask(system, user_text, images, model):
            seen.update(system=system, user=user_text, images=images)
            return ('{"prompt": "kael_hero, silver-haired knight on a cliff", "negative": "text", '
                    '"aspect": "21:9", "explanation": "ok"}'), {"provider": "fake", "model": "m"}

        orig, prompt_assist._ask = prompt_assist._ask, fake_ask
        try:
            out = prompt_assist.single("Kael no penhasco", "texto da cena", ["data:image/png;base64,AA"],
                                       characters=[{"id": "k", "name": "Kael", "look": "silver hair",
                                                    "image_data": ["data:image/png;base64,BB"]}])
        finally:
            prompt_assist._ask = orig
        self.assertIs(seen["system"], prompt_assist.SINGLE_SYSTEM)
        self.assertIn("Kael no penhasco", seen["user"])
        self.assertIn("texto da cena", seen["user"])
        self.assertEqual(len(seen["images"]), 2)  # a do usuário + a da ficha
        self.assertEqual(out["prompt"], "kael_hero, silver-haired knight on a cliff")
        self.assertEqual(out["aspect"], "1:1")  # proporção inválida vira 1:1
        self.assertEqual((out["negative"], out["characters_used"], out["provider"]), ("text", ["k"], "fake"))


class McpTest(unittest.TestCase):
    def test_tools_list_and_old_names(self):
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "nao_existe", "arguments": {}}}]
        p = subprocess.run([sys.executable, os.path.join(ROOT, "studio_mcp.py")],
                           input="\n".join(json.dumps(m) for m in msgs) + "\n", capture_output=True, text=True,
                           encoding="utf-8", timeout=30)
        out = [json.loads(line) for line in p.stdout.splitlines() if line.strip()]
        self.assertEqual(out[0]["result"]["serverInfo"]["name"], "biazzitech-ai-studio")
        names = [t["name"] for t in out[1]["result"]["tools"]]
        for n in ("studio_code", "studio_text", "free_image_create", "ai_providers_status"):
            self.assertIn(n, names)
        self.assertIn("desconhecida", out[2]["result"]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
