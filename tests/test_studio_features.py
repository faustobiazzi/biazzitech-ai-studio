"""Fichas de personagem, modelos de página/onomatopeias no auxiliar e exportação para o Godot."""
import base64
import json
import os
import struct
import unittest
import zipfile
import zlib

from _env import DATA, TMP, write_env, clear_data

import characters
import comic_layouts
import godot_export
import prompt_assist
import provider_router as router


def make_png(path, w, h, visible):
    """PNG RGBA; visible(x, y) -> bool define os pixels opacos."""
    raw = b""
    for y in range(h):
        raw += b"\x00" + b"".join(b"\xff\x00\x00\xff" if visible(x, y) else b"\x00\x00\x00\x00" for x in range(w))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(data)
    return data


TINY_PNG = "data:image/png;base64," + base64.b64encode(
    make_png(os.path.join(TMP, "tiny.png"), 2, 2, lambda x, y: True)).decode()


class CharactersTest(unittest.TestCase):
    def setUp(self):
        clear_data()

    def test_save_detect_and_delete(self):
        c = characters.save_character({"name": "José Ferreira", "aliases": "Zé, Capitão",
                                       "look": "tall man, grey beard", "new_images": [TINY_PNG]})
        self.assertEqual(c["id"], "jose_ferreira")
        self.assertEqual(c["aliases"], ["Zé", "Capitão"])
        self.assertEqual(len(c["images"]), 1)
        self.assertTrue(characters.image_data_url(c["images"][0]).startswith("data:image/png"))
        self.assertEqual(characters.detect("o capitao entra na sala"), ["jose_ferreira"])  # sem acento
        self.assertEqual(characters.detect("JOSE FERREIRA corre"), ["jose_ferreira"])
        self.assertEqual(characters.detect("josefina corre"), [])  # palavra inteira
        c2 = characters.save_character({"name": "José Ferreira"})
        self.assertEqual(c2["id"], "jose_ferreira_2")  # mesmo nome não sobrescreve
        upd = characters.save_character({"id": c["id"], "name": "José", "remove_images": c["images"]})
        self.assertEqual(upd["images"], [])
        self.assertIn("José", characters.prompt_block([upd]))
        characters.delete_character(c["id"])
        self.assertIsNone(characters.get(c["id"]))

    def test_limits_and_bad_input(self):
        with self.assertRaises(characters.CharacterError):
            characters.save_character({"name": ""})
        with self.assertRaises(characters.CharacterError):
            characters.save_character({"name": "A", "new_images": ["data:text/plain;base64,AAA"]})
        with self.assertRaises(characters.CharacterError):
            characters.save_character({"name": "A", "new_images": [TINY_PNG] * 5})
        self.assertIsNone(characters.image_path("../users.json"))


class LayoutsTest(unittest.TestCase):
    def test_layouts_are_valid(self):
        data = comic_layouts.layouts()
        W, H = data["page"]["width"], data["page"]["height"]
        ids = set()
        for lay in data["layouts"]:
            ids.add(lay["id"])
            self.assertEqual(lay["count"], len(lay["panels"]))
            for p in lay["panels"]:
                self.assertEqual(len(p["poly"]), 4)
                for x, y in p["poly"]:
                    self.assertTrue(0 <= x <= W and 0 <= y <= H, (lay["id"], x, y))
                self.assertIn(p["aspect"], comic_layouts.ASPECTS)
        self.assertEqual(comic_layouts.get("grade_4")["count"], 4)
        self.assertEqual(comic_layouts.get("faixas_3")["panels"][0]["aspect"], "16:9")
        self.assertEqual(comic_layouts.get("colunas_3")["panels"][0]["aspect"], "9:16")
        self.assertIn("dinamico_5", ids)


class PlanTest(unittest.TestCase):
    def setUp(self):
        clear_data()
        write_env()
        router.load_env()
        self.sent = {}
        self._orig = prompt_assist._ask

        def fake_ask(system, user_text, images, model):
            self.sent = {"system": system, "user": user_text, "images": images}
            return self.reply, {"model": "fake", "provider": "teste"}
        prompt_assist._ask = fake_ask

    def tearDown(self):
        prompt_assist._ask = self._orig

    def test_layout_sfx_and_characters(self):
        self.reply = json.dumps({"style": "x", "layout": "", "panels": [
            {"n": 1, "prompt": "a", "aspect": "1:1", "sfx": [{"text": "SOC!", "style": "hachurado", "position": "left",
                                                              "size": "l", "angle": 99}]},
            {"n": 2, "prompt": "b", "sfx": [{"text": ""}, {"text": "BANG", "style": "?", "position": "?"}], "bleed": 1},
            {"n": 3, "prompt": "c"}, {"n": 4, "prompt": "d"}]})
        hero = {"id": "heroi", "name": "Herói", "look": "red cape", "aliases": [], "image_data": [TINY_PNG, TINY_PNG]}
        d = prompt_assist.plan("página de 4 quadros", "texto", [TINY_PNG], "groq/x", characters=[hero],
                               layout="dinamico_4", layout_text="cortes inclinados", sfx_text="SOC! hachurado no 1")
        self.assertEqual(d["layout"], "dinamico_4")
        self.assertEqual([p["aspect"] for p in d["panels"]],
                         [p["aspect"] for p in comic_layouts.get("dinamico_4")["panels"]])
        self.assertEqual(d["panels"][0]["sfx"][0]["angle"], 45)
        self.assertEqual(d["panels"][1]["sfx"], [{"text": "BANG", "style": "neutro", "position": "right", "size": "m",
                                                  "angle": 0}])
        self.assertTrue(d["panels"][1]["bleed"])
        self.assertEqual(len(self.sent["images"]), 3)  # 1 do usuário + 2 da ficha
        for piece in ("KNOWN CHARACTERS", "red cape", "fixed layout 'dinamico_4'", "cortes inclinados",
                      "SOC! hachurado", "SFX MODE: overlay"):
            self.assertIn(piece, self.sent["user"])

    def test_auto_layout_must_match_panel_count(self):
        self.reply = json.dumps({"layout": "grade_6", "panels": [{"prompt": "a"}, {"prompt": "b"}, {"prompt": "c"}]})
        d = prompt_assist.plan("3 quadros", layout="auto", sfx_mode="draw")
        self.assertEqual(comic_layouts.get(d["layout"])["count"], 3)
        self.assertEqual(d["sfx_mode"], "draw")
        self.assertIn("Choose one of these layouts", self.sent["user"])

    def test_no_page(self):
        self.reply = json.dumps({"panels": [{"prompt": "a", "aspect": "16:9"}]})
        d = prompt_assist.plan("uma ilustração")
        self.assertEqual(d["layout"], "")
        self.assertEqual(d["panels"][0]["aspect"], "16:9")

    def test_retries_another_model_when_json_is_broken(self):
        write_env(GEMINI_API_KEY="x", GROQ_API_KEY="y")
        router.load_env()
        answers = iter([("", {"provider": "gemini", "model": "g"}),                    # vazio
                        ('{"panels": [', {"provider": "openrouter", "model": "o"}),     # cortado
                        ('{"panels": [{"prompt": "ok"}]}', {"provider": "groq", "model": "q"})])
        calls = []

        def fake(system, user, images, model):
            calls.append(model)
            return next(answers)
        prompt_assist._ask = fake
        d = prompt_assist.plan("um quadro")
        self.assertEqual(d["panels"][0]["prompt"], "ok")
        self.assertEqual(d["provider"], "groq")
        self.assertEqual(len(calls), 3)

    def test_reasoning_text_is_used_when_content_is_empty(self):
        prompt_assist._ask = self._orig
        orig_cc = router.chat_completion
        router.chat_completion = lambda payload, timeout=90: (
            {"choices": [{"message": {"content": "", "reasoning_content": 'pensando... {"look": "tall"}'}}]},
            {"provider": "p", "model": "m"})
        try:
            raw, _ = prompt_assist._ask("s", "u", [], "auto")
            self.assertIn('{"look": "tall"}', raw)
        finally:
            router.chat_completion = orig_cc

    def test_describe_character(self):
        self.reply = '{"look": "young woman, short black hair", "notes": "ok"}'
        d = prompt_assist.describe_character([TINY_PNG], "Ana")
        self.assertEqual(d["look"], "young woman, short black hair")
        with self.assertRaises(prompt_assist.AssistError):
            prompt_assist.describe_character([])


class GodotTest(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.join(TMP, "galeria")
        os.makedirs(self.dir, exist_ok=True)

    def resolver(self, name):
        p = os.path.join(self.dir, name)
        return p if os.path.isfile(p) else None

    def test_spriteframes(self):
        # folha 4x2 de 16x16; o último quadro da 2ª linha está vazio
        make_png(os.path.join(self.dir, "heroi.png"), 64, 32, lambda x, y: not (x >= 48 and y >= 16))
        out = godot_export.export({"image": "heroi.png", "frame_w": 16, "frame_h": 16, "name": "Herói Azul",
                                   "res_path": "res://personagens/heroi",
                                   "animations": [{"name": "Parado", "row": 0, "fps": 6},
                                                  {"name": "andar", "row": 1, "fps": 10, "loop": False}]},
                                  self.dir, self.resolver)
        self.assertEqual((out["columns"], out["rows"]), (4, 2))
        self.assertEqual(out["texture_path"], "res://personagens/heroi/heroi_azul.png")
        self.assertEqual([a["frames"] for a in out["animations"]], [4, 3])  # quadro vazio fica de fora
        with open(os.path.join(out["folder"], "heroi_azul.tres"), encoding="utf-8") as f:
            tres = f.read()
        self.assertIn('[gd_resource type="SpriteFrames" load_steps=9 format=3]', tres)
        self.assertIn('path="res://personagens/heroi/heroi_azul.png"', tres)
        self.assertIn("region = Rect2(32, 16, 16, 16)", tres)
        self.assertNotIn("Rect2(48, 16", tres)
        self.assertIn('"name": &"parado"', tres)
        self.assertIn('"loop": false', tres)
        self.assertIn('"speed": 10.0', tres)
        with zipfile.ZipFile(os.path.join(self.dir, "godot", out["zip"])) as z:
            self.assertIn("heroi_azul/heroi_azul.tres", z.namelist())
        self.assertIsNotNone(godot_export.zip_path(out["zip"], self.dir))
        self.assertIsNone(godot_export.zip_path("../x.zip", self.dir))

    def test_tileset_skips_empty_cells(self):
        make_png(os.path.join(self.dir, "tiles.png"), 32, 32, lambda x, y: x < 16 or y < 16)  # 3 de 4 com pixels
        out = godot_export.export({"image": "tiles.png", "kind": "tileset", "frame_w": 16, "frame_h": 16},
                                  self.dir, self.resolver)
        self.assertEqual(out["tiles"], 3)
        with open(os.path.join(out["folder"], "tiles_tileset.tres"), encoding="utf-8") as f:
            tres = f.read()
        self.assertIn("texture_region_size = Vector2i(16, 16)", tres)
        self.assertIn("0:1/0 = 0", tres)
        self.assertNotIn("1:1/0 = 0", tres)

    def test_errors(self):
        make_png(os.path.join(self.dir, "p.png"), 8, 8, lambda x, y: True)
        with self.assertRaises(godot_export.ExportError):
            godot_export.export({"image": "p.png", "frame_w": 16, "frame_h": 16}, self.dir, self.resolver)
        with self.assertRaises(godot_export.ExportError):
            godot_export.export({"image": "nao_existe.png", "frame_w": 8, "frame_h": 8}, self.dir, self.resolver)
        with open(os.path.join(self.dir, "foto.jpg"), "wb") as f:
            f.write(b"\xff\xd8\xff" + b"0" * 30)
        with self.assertRaises(godot_export.ExportError):
            godot_export.export({"image": "foto.jpg", "frame_w": 8, "frame_h": 8}, self.dir, self.resolver)


if __name__ == "__main__":
    unittest.main()
