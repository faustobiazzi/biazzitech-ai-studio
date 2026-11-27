"""Conversas guardadas por usuário, memória (compactação/limpeza) e visibilidade de imagens e conversas."""
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from _env import write_env, clear_data

import access_control as access
import conversations
import provider_router as router
import studio_server


class ConversationStoreTest(unittest.TestCase):
    def setUp(self):
        clear_data()

    def test_context_memory_compaction_and_clear(self):
        c = conversations.create("ana", preset="lore")
        for i in range(10):
            conversations.append(c["id"], "ana", "user", f"pergunta {i} " + "x" * 50)
            conversations.append(c["id"], "ana", "assistant", f"resposta {i}")
        conv = conversations.get(c["id"], "ana", False)
        self.assertTrue(conv["title"].startswith("pergunta 0"))
        ctx = conversations.build_context(conv, "Você é roteirista.", budget=300)
        self.assertEqual(ctx[0]["role"], "system")
        self.assertEqual(ctx[1]["role"], "user")              # contexto começa por pergunta
        self.assertEqual(ctx[-1]["content"], "resposta 9")    # o mais recente sempre entra
        self.assertLess(len(ctx), 21)                         # o orçamento cortou as antigas

        seen = {}

        def fake_ask(payload):
            seen["text"] = payload["messages"][1]["content"]
            return "- objetivo: escrever a lore\n- personagem: Kael"
        r = conversations.compact(c["id"], "ana", ask=fake_ask)
        self.assertEqual(r["summarized"], 20 - conversations.KEEP_RECENT)
        self.assertIn("pergunta 0", seen["text"])
        self.assertNotIn("resposta 9", seen["text"])          # as últimas não entram no resumo
        conv = conversations.get(c["id"], "ana", False)
        ctx = conversations.build_context(conv, "Você é roteirista.")
        self.assertIn("personagem: Kael", ctx[0]["content"])  # memória vai junto da instrução
        self.assertEqual(len(ctx), 1 + conversations.KEEP_RECENT)
        with self.assertRaises(conversations.ConversationError):
            conversations.compact(c["id"], "ana", ask=fake_ask)  # nada novo para compactar

        conversations.clear(c["id"], "ana")
        conv = conversations.get(c["id"], "ana", False)
        self.assertEqual((conv["messages"], conv["memory"], conv["summarized_upto"]), ([], "", 0))

    def test_visibility_and_permissions(self):
        a = conversations.create("ana")
        b = conversations.create("bia")
        self.assertEqual(conversations.list_for("ana", False)[0]["id"], a["id"])
        self.assertEqual(len(conversations.list_for("adm", True, everyone=True)), 2)
        with self.assertRaises(conversations.ConversationError):
            conversations.get(b["id"], "ana", False)         # usuário comum não vê a dos outros
        self.assertEqual(conversations.get(b["id"], "adm", True)["owner"], "bia")  # admin vê
        with self.assertRaises(conversations.ConversationError):
            conversations.append(b["id"], "adm", "user", "oi")  # admin só lê
        with self.assertRaises(conversations.ConversationError):
            conversations.delete(b["id"], "ana", False)
        conversations.delete(b["id"], "adm", True)
        with self.assertRaises(conversations.ConversationError):
            conversations.get("../../etc", "ana", True)


class AnchorTest(unittest.TestCase):
    """Contexto inicial guardado à parte, resgate quando o usuário reclama e redefinição do contexto."""
    def setUp(self):
        clear_data()

    def talk(self, cid, text, intent="auto"):
        it = conversations.detect_intent(text) if intent == "auto" else intent
        conversations.append(cid, "ana", "user", text, intent=it)
        conversations.append(cid, "ana", "assistant", "ok: " + text[:20])
        return it

    def test_detect_intent(self):
        self.assertEqual(conversations.detect_intent("você esqueceu o que eu pedi lá no início"), "rescue")
        self.assertEqual(conversations.detect_intent("como eu disse antes, o Kael é ruivo"), "rescue")
        self.assertEqual(conversations.detect_intent("o contexto mudou: agora é um jogo de terror"), "reset")
        self.assertEqual(conversations.detect_intent("esqueça o que eu disse, isso não vale mais"), "reset")
        self.assertIsNone(conversations.detect_intent("escreva o diálogo do ferreiro"))

    def test_anchors_capture_opening_topic_then_stop(self):
        c = conversations.create("ana")
        self.talk(c["id"], "Jogo de plataforma em Godot com o herói Kael na cidade de Vharn")
        self.talk(c["id"], "Kael usa espada curta e tem cabelo prateado")
        self.talk(c["id"], "A cidade de Vharn é portuária e chuvosa")
        self.talk(c["id"], "O vilão de Vharn persegue o Kael pelo porto")   # 4ª: mesmo assunto, entra
        self.talk(c["id"], "Me explica herança de classes em Python")       # outro assunto: fecha a captura
        self.talk(c["id"], "Kael encontra um mapa em Vharn")                # depois de fechar, não entra mais
        conv = conversations.get(c["id"], "ana", False)
        self.assertEqual(len(conv["anchors"]), 4)
        self.assertTrue(conv["anchors_closed"])
        ctx = conversations.build_context(conv, "S")
        self.assertNotIn("PEDIDOS INICIAIS", ctx[0]["content"])  # âncoras são só consulta

    def test_rescue_brings_back_opening_and_old_snippets(self):
        c = conversations.create("ana")
        self.talk(c["id"], "Kael tem cabelo prateado e usa uma espada curta de bronze")
        self.talk(c["id"], "Kael nasceu em Vharn")
        self.talk(c["id"], "Kael tem medo de água")
        for i in range(12):
            self.talk(c["id"], f"pergunta solta numero {i} sobre shaders " + "z" * 200)
        conv = conversations.get(c["id"], "ana", False)
        conv["summarized_upto"] = len(conv["messages"]) - 4  # o início já saiu do contexto
        it = self.talk(c["id"], "você esqueceu o que eu disse no início sobre a espada do Kael")
        self.assertEqual(it, "rescue")
        conv = conversations.get(c["id"], "ana", False)
        self.assertEqual(len(conv["anchors"]), 3)  # a reclamação não vira âncora
        conv["summarized_upto"] = len(conv["messages"]) - 4
        ctx = conversations.build_context(conv, "S", intent="rescue", query="esqueceu a espada do Kael")
        self.assertIn("PEDIDOS INICIAIS", ctx[0]["content"])
        self.assertIn("espada curta de bronze", ctx[0]["content"])
        self.assertGreater(conv["_last_rescue"]["snippets"], 0)

    def test_reset_replaces_opening_and_rewrites_memory(self):
        c = conversations.create("ana")
        self.talk(c["id"], "Jogo de fantasia medieval com o Kael")
        self.talk(c["id"], "Kael é um cavaleiro")
        self.talk(c["id"], "O castelo de Kael fica no norte")
        conversations.set_memory(c["id"], "ana", "- cenário: fantasia medieval\n- Kael: cavaleiro")
        it = self.talk(c["id"], "O contexto mudou: agora é ficção científica, Kael é piloto de nave")
        self.assertEqual(it, "reset")
        conv = conversations.get(c["id"], "ana", False)
        self.assertEqual([a["text"][:20] for a in conv["anchors"]], ["O contexto mudou: ag"])
        self.assertTrue(conv["context_reset"])
        conv["summarized_upto"] = len(conv["messages"]) - 2  # o começo já saiu do contexto
        ctx = conversations.build_context(conv, "S", intent="reset", query="ficção científica Kael piloto")
        self.assertIn("CONTEXTO VIGENTE", ctx[0]["content"])
        self.assertIn("ACABOU DE DIZER QUE O CONTEXTO MUDOU", ctx[0]["content"])
        self.assertIn("TRECHOS DA CONVERSA", ctx[0]["content"])  # achou menções ao Kael para reintegrar
        # nas respostas seguintes o contexto novo continua valendo
        self.talk(c["id"], "Descreve a nave")
        later = conversations.build_context(conversations.get(c["id"], "ana", False), "S")
        self.assertIn("piloto de nave", later[0]["content"])
        mem = conversations.rebase_memory(c["id"], "ana", ask=lambda p: "Contexto atual: ficção científica\n- Kael: piloto")
        self.assertIn("ficção científica", mem)
        self.assertNotIn("medieval", conversations.get(c["id"], "ana", False)["memory"])
        anchors = conversations.get(c["id"], "ana", False)["anchors"]
        self.assertEqual(len(anchors), 1)  # depois de redefinir, só a declaração vira contexto (o resto: fixar)
        conversations.remove_anchor(c["id"], "ana", 0)
        self.assertEqual(conversations.get(c["id"], "ana", False)["anchors"], [])


class OwnershipServerTest(unittest.TestCase):
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
        _, _, self.t_adm = access.add_user("adm", "segredo1", ["chat", "imagens", "admin"])
        _, _, self.t_ana = access.add_user("ana", "segredo2", ["chat", "imagens"])
        _, _, self.t_bia = access.add_user("bia", "segredo3", ["chat", "imagens"])
        access.set_config(auth_local=True)
        self.orig_chat = router.chat_completion
        router.chat_completion = lambda payload, **kw: (
            {"choices": [{"message": {"content": "eco: " + payload["messages"][-1]["content"]}}], "model": "m"},
            {"provider": "fake", "model": "m"})

    def tearDown(self):
        router.chat_completion = self.orig_chat
        access.set_config(auth_local=False)

    def call(self, path, body=None, token=None):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_chat_is_saved_per_user_and_admin_sees_all(self):
        st, d = self.call("/api/chat", {"content": "oi, sou a Ana", "model": "auto", "system": "s"}, self.t_ana)
        self.assertEqual(st, 200, d)
        self.assertEqual(d["reply"], "eco: oi, sou a Ana")
        cid = d["conversation_id"]
        st, d = self.call("/api/chat", {"conversation_id": cid, "content": "lembra?", "system": "s"}, self.t_ana)
        self.assertEqual(st, 200)
        st, d = self.call(f"/api/conversations/{cid}", token=self.t_ana)
        self.assertEqual([m["role"] for m in d["conversation"]["messages"]], ["user", "assistant", "user", "assistant"])
        # Bia não vê nem escreve na conversa da Ana
        self.assertEqual(self.call(f"/api/conversations/{cid}", token=self.t_bia)[0], 404)
        self.assertEqual(self.call("/api/conversations", token=self.t_bia)[1]["conversations"], [])
        self.assertEqual(self.call("/api/chat", {"conversation_id": cid, "content": "x"}, self.t_bia)[0], 403)
        # admin vê (só leitura)
        st, d = self.call("/api/conversations?all=1", token=self.t_adm)
        self.assertEqual([c["owner"] for c in d["conversations"]], ["ana"])
        st, d = self.call(f"/api/conversations/{cid}", token=self.t_adm)
        self.assertFalse(d["conversation"]["can_edit"])
        # limpeza pela API
        st, d = self.call("/api/conversations", {"action": "clear", "id": cid}, self.t_ana)
        self.assertEqual(st, 200, d)
        self.assertEqual(self.call(f"/api/conversations/{cid}", token=self.t_ana)[1]["conversation"]["messages"], [])

    def test_admin_continues_conversations_made_on_the_pc_without_login(self):
        local = conversations.create("local")
        conversations.append(local["id"], "local", "user", "conversa feita no PC, sem login")
        st, d = self.call("/api/conversations", token=self.t_adm)
        self.assertIn(local["id"], [c["id"] for c in d["conversations"]])   # aparece como dele
        self.assertIn("local", d["mine"])
        st, d = self.call(f"/api/conversations/{local['id']}", token=self.t_adm)
        self.assertTrue(d["conversation"]["can_edit"])
        st, d = self.call("/api/chat", {"conversation_id": local["id"], "content": "continuando pela rede"}, self.t_adm)
        self.assertEqual(st, 200, d)
        # usuário comum não vê nem continua
        self.assertEqual(self.call("/api/conversations", token=self.t_ana)[1]["conversations"], [])
        self.assertEqual(self.call(f"/api/conversations/{local['id']}", token=self.t_ana)[0], 404)

    def test_ai_options_question_undo_and_pins(self):
        calls = []

        def fake_chat(payload, **kw):
            system = payload["messages"][0]["content"]
            calls.append(system[:30])
            if system is conversations.INTENT_SYSTEM:
                last = payload["messages"][1]["content"]
                intent = "none" if "personagem grita" in last else "reset"
                return {"choices": [{"message": {"content": '{"intent": "%s"}' % intent}}]}, {"provider": "f"}
            if system is conversations.PARTIAL_SYSTEM:
                return {"choices": [{"message": {"content": '{"keep": [1, 2], "removed": [3]}'}}]}, {"provider": "f"}
            return {"choices": [{"message": {"content": "resposta"}}], "model": "m"}, {"provider": "fake", "model": "m"}
        router.chat_completion = fake_chat
        chat = lambda cid, text: self.call("/api/chat", {"conversation_id": cid, "content": text, "system": "s"}, self.t_ana)[1]

        d = chat("", "Lore: Kael é cavaleiro")
        cid = d["conversation_id"]
        chat(cid, "Kael mora no castelo do norte")
        chat(cid, "Kael usa espada de bronze")
        # 1ª vez que aparece mudança de contexto: troca tudo (padrão) e PERGUNTA sobre as opções com IA
        d = chat(cid, "O contexto mudou: Kael agora usa machado")
        self.assertEqual(d["intent"], "reset")
        self.assertIn("CONSULTA EXTRA", d["question"])
        self.assertTrue(d["can_undo"])
        self.assertEqual(len(d["removed_anchors"]), 3)
        conv = conversations.get(cid, "ana", False)
        self.assertEqual(conv["messages"][-1]["content"], conversations.AI_OPTIONS_QUESTION)
        # desfazer: as âncoras voltam
        self.assertEqual(self.call("/api/conversations", {"action": "undo_reset", "id": cid}, self.t_ana)[0], 200)
        conv = conversations.get(cid, "ana", False)
        self.assertEqual(len(conv["anchors"]), 3)
        self.assertFalse(conv["context_reset"])
        # "do it" responde a pergunta sem gastar consulta
        n = len(calls)
        d = chat(cid, "do it")
        self.assertEqual(d["provider"], "painel")
        self.assertEqual(len(calls), n)
        self.assertTrue(conversations.get_prefs("ana")["partial_reset"])
        self.assertNotIn("do it", [a["text"] for a in conversations.get(cid, "ana", False)["anchors"]])
        # com as opções: fala de personagem não dispara; mudança real tira só o que conflita
        d = chat(cid, "O personagem grita: esqueça o que eu disse, isso não vale mais!")
        self.assertIsNone(d["intent"])
        self.assertEqual(d["extra_calls"], 1)
        d = chat(cid, "O contexto mudou: a espada agora é de ferro")
        self.assertEqual(d["intent"], "reset")
        self.assertEqual(d["extra_calls"], 2)
        self.assertEqual(d["removed_anchors"], ["Kael usa espada de bronze"])
        conv = conversations.get(cid, "ana", False)
        self.assertEqual([a["text"][:12] for a in conv["anchors"]], ["Lore: Kael é", "Kael mora no", "O contexto m"])
        # fixar uma mensagem antiga: entra no contexto mesmo fora da janela recente
        self.assertEqual(self.call("/api/conversations", {"action": "pin", "id": cid, "index": 2}, self.t_ana)[0], 200)
        conv = conversations.get(cid, "ana", False)
        conv["summarized_upto"] = len(conv["messages"]) - 2
        ctx = conversations.build_context(conv, "s")
        self.assertIn("MENSAGENS FIXADAS", ctx[0]["content"])
        self.assertIn("castelo do norte", ctx[0]["content"])

    def test_images_are_visible_only_to_owner_and_admins(self):
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
        a = studio_server.save_output_image(png, "img_ana", ".png", {"owner": "ana"})
        studio_server.save_output_image(png, "img_bia", ".png", {"owner": "bia"})
        studio_server.save_output_image(png, "antiga", ".png", {})  # sem dono: só admin
        names = lambda tok: sorted(i["file_name"] for i in self.call("/api/images", token=tok)[1]["images"])
        self.assertEqual(names(self.t_ana), ["img_ana.png"])
        self.assertEqual(names(self.t_adm), ["antiga.png", "img_ana.png", "img_bia.png"])
        req = urllib.request.Request(self.base + "/imagens/" + a["file_name"], headers={"Authorization": f"Bearer {self.t_bia}"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(ctx.exception.code, 404)
        self.assertEqual(self.call("/api/image/delete", {"name": a["file_name"]}, self.t_bia)[0], 404)
        self.assertEqual(self.call("/api/image/delete", {"name": a["file_name"]}, self.t_ana)[0], 200)


if __name__ == "__main__":
    unittest.main()
