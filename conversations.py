#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Conversas do chat guardadas no servidor, por usuário, com memória (contexto) compactável.

- Cada conversa é um .json em <pasta de dados>/conversas/: dono, título, mensagens e a MEMÓRIA
  (um resumo do que já foi conversado, escrito pela IA ao compactar e editável pelo usuário).
- Contexto enviado ao modelo = instrução do modo + memória + as mensagens mais recentes que couberem
  no orçamento. As mensagens antigas continuam guardadas (para reler), mas saem do contexto.
- Compactar: a IA junta a memória atual com as mensagens que ainda não foram resumidas (menos as
  últimas) e escreve uma memória nova. Acontece sozinho quando o contexto passa do limite.
- Limpar: apaga mensagens e memória (a conversa recomeça do zero, com o mesmo nome).
- Contexto inicial (âncoras): as primeiras perguntas do usuário (3 a 10, enquanto forem do mesmo assunto)
  ficam guardadas à parte, como consulta. Não entram em toda resposta; são resgatadas quando o usuário
  reclama de perda de contexto ("você esqueceu", "como eu disse no início"...), junto com os trechos
  antigos da conversa que tratam do mesmo assunto.
- Redefinir: se o usuário diz que o contexto mudou ("isso não vale mais", "o contexto agora é..."), as
  âncoras antigas saem, a mensagem dele vira o contexto vigente (enviado em toda resposta), a IA procura
  na conversa o que se liga ao novo contexto e a memória é reescrita sem o que ficou obsoleto.
- Desfazer: uma redefinição detectada por engano (ex.: fala de personagem) pode ser desfeita com um clique.
- Fixar (📌): qualquer mensagem pode ser fixada e vai junto em toda resposta, mesmo depois de compactar.
- Opcionais (gastam consulta extra, o usuário decide no próprio chat na 1ª vez):
  confirmar com a IA se a frase era mesmo reclamação/mudança de contexto, e redefinição parcial
  (a IA tira só o que conflita com o contexto novo, em vez de trocar tudo).
- Visibilidade: cada usuário vê só as suas; administradores veem as de todos (só leitura nas dos outros).
"""

import json
import os
import re
import secrets
import threading
import time

import provider_router as router

CONTEXT_BUDGET = 24000      # caracteres de mensagens recentes no contexto (~6 mil tokens)
AUTO_COMPACT_AT = 32000     # acima disso (mensagens fora da memória), compacta sozinho
KEEP_RECENT = 6             # mensagens que nunca entram no resumo (ficam inteiras no contexto)
MAX_MEMORY = 6000           # tamanho máximo da memória
ANCHOR_MIN = 3             # as 3 primeiras perguntas sempre viram âncora
ANCHOR_MAX = 10            # até 10, enquanto continuarem no mesmo assunto
ANCHOR_CHARS = 2000        # tamanho máximo guardado de cada âncora
RESCUE_SNIPPETS = 4        # trechos antigos resgatados junto com as âncoras
_lock = threading.RLock()

RESCUE_RE = re.compile(
    r"(esque(ceu|cendo|ceste)|perdeu o (fio|contexto)|perdendo o (fio|contexto)|n[aã]o (se )?lembr|"
    r"como eu (te )?(disse|falei|pedi|expliquei)|j[aá] (te )?(disse|falei|expliquei)|"
    r"(l[aá]|bem) no (in[ií]cio|come[cç]o)|desde o (in[ií]cio|come[cç]o)|voltando ao (in[ií]cio|come[cç]o)|"
    r"(saiu|fugiu|fugindo|saindo) do (assunto|contexto|foco)|se perdeu|perdeu o foco|contexto (original|inicial))",
    re.IGNORECASE)
RESET_RE = re.compile(
    r"(contexto (mudou|agora [eé]|novo|n[aã]o [eé] mais)|mudei o (contexto|assunto|plano)|mudou o (contexto|plano)|"
    r"(isso|aquilo|o (in[ií]cio|come[cç]o)) n[aã]o vale mais|n[aã]o vale mais|"
    r"(esque[cç]a|desconsidere|ignore|descarte) (o que eu (disse|falei)|o (in[ií]cio|come[cç]o)|o contexto)|"
    r"(a partir de agora|daqui pra frente|de agora em diante),? o (contexto|objetivo|plano))",
    re.IGNORECASE)
_STOP = set("""para pela pelo pelos pelas como mais isso essa esse esta este aqui agora quando onde porque sobre
entre tambem também muito muita mesmo ainda depois antes tudo nada cada qual quais seus suas minha minhas meus
voce você vocês voces dele dela deles delas fazer faz feito pode podem deve devem seria sendo estou está estao
estão tenho temos fica ficar outro outra outros outras algum alguma alguns algumas certo sim não nao então entao
qual quero queria disse falei pedi expliquei início inicio começo comeco contexto conversa assunto""".split())


def detect_intent(text):
    """'reset' (o usuário diz que o contexto mudou), 'rescue' (reclama de perda de contexto) ou None."""
    t = text or ""
    if RESET_RE.search(t):
        return "reset"
    if RESCUE_RE.search(t):
        return "rescue"
    return None


def _words(text):
    import unicodedata
    t = unicodedata.normalize("NFKD", (text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return {w for w in re.findall(r"[a-z0-9_]{4,}", t) if w not in _STOP}


def _related(text, anchors):
    """Mesmo assunto das âncoras: divide pelo menos 2 palavras relevantes (ou 1, se a pergunta for curta)."""
    words = _words(text)
    pool = set().union(*(_words(a["text"]) for a in anchors)) if anchors else set()
    common = len(words & pool)
    return common >= 2 or (common >= 1 and len(words) <= 6)


def _relevant_messages(conv, query_words, exclude, limit=RESCUE_SNIPPETS):
    """Mensagens da conversa que mais tratam das palavras pedidas (fora as já no contexto)."""
    scored = []
    for i, m in enumerate(conv["messages"]):
        if i in exclude:
            continue
        score = len(_words(m.get("content")) & query_words)
        if score:
            scored.append((score, i))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return sorted(i for _, i in scored[:limit])
_ID_RE = re.compile(r"^[a-z0-9]{12,40}$")
PIN_BUDGET = 8000          # caracteres de mensagens fixadas no contexto
AFFIRM_RE = re.compile(r"^\s*(sim|s|pode( ser)?|fa[cç]a( isso)?|faz( isso)?|do it|manda( bala| ver)?|ok(ay)?|claro|"
                       r"bora|ativa(r)?|yes|yep|y|quero|com certeza|certo|beleza|blz|vai|aceito)\b", re.IGNORECASE)
DENY_RE = re.compile(r"^\s*(n[aã]o|n|nope|no|deixa( pra l[aá])?|agora n[aã]o|dispenso|dispensa|nem|negativo|"
                     r"desativa(r)?|melhor n[aã]o)\b", re.IGNORECASE)
AI_OPTIONS_QUESTION = (
    "💡 Posso deixar isso mais esperto usando a IA, mas cada uso gasta UMA CONSULTA EXTRA (tokens):\n"
    "• confirmar se a sua frase era mesmo reclamação/mudança de contexto (evita engano com fala de personagem);\n"
    "• na mudança de contexto, tirar só o que conflita com o novo, em vez de trocar o contexto inicial inteiro.\n"
    "Quer ativar? Responda \"sim\" (ou faça, do it, manda bala...) ou \"não\". Dá para mudar depois na 🧠 Memória.")

COMPACT_SYSTEM = (
    "Você mantém a MEMÓRIA de uma conversa entre um usuário e um assistente. Receberá a memória atual (pode "
    "estar vazia) e mensagens novas. Escreva a memória atualizada em português do Brasil, em tópicos curtos: "
    "objetivo do usuário, decisões tomadas, fatos e preferências que ele informou, nomes (personagens, arquivos, "
    "funções), código ou trechos que ainda importam (resumidos) e o que ficou pendente. Descarte conversa fiada "
    "e o que já foi resolvido e não importa mais. Não invente nada. Responda SÓ com a memória, no máximo ~"
    f"{MAX_MEMORY // 5} palavras."
)


class ConversationError(Exception):
    pass


def _dir():
    d = os.path.join(router.data_dir(), "conversas")
    os.makedirs(d, exist_ok=True)
    return d


def _path(cid):
    if not isinstance(cid, str) or not _ID_RE.match(cid):
        raise ConversationError("Conversa inválida.")
    return os.path.join(_dir(), cid + ".json")


def _save(conv):
    conv["updated"] = time.time()
    path = _path(conv["id"])
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(conv, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return conv


def _load(cid):
    try:
        with open(_path(cid), "r", encoding="utf-8") as f:
            conv = json.load(f)
    except (OSError, ValueError):
        raise ConversationError("Conversa não encontrada.")
    conv.setdefault("messages", [])
    conv.setdefault("memory", "")
    conv.setdefault("summarized_upto", 0)
    conv.setdefault("anchors", [])
    conv.setdefault("anchors_closed", False)
    conv.setdefault("context_reset", False)
    conv.setdefault("pins", [])
    conv.setdefault("reset_id", 0)
    return conv


def _prefs_path():
    return os.path.join(_dir(), "_preferencias.json")


def get_prefs(owner):
    """Opções do usuário: ai_confirm / partial_reset (None = ainda não perguntado)."""
    try:
        with open(_prefs_path(), "r", encoding="utf-8") as f:
            return dict((json.load(f) or {}).get(_primary(owner)) or {})
    except (OSError, ValueError):
        return {}


def set_prefs(owner, **values):
    with _lock:
        try:
            with open(_prefs_path(), "r", encoding="utf-8") as f:
                data = json.load(f) or {}
        except (OSError, ValueError):
            data = {}
        cur = data.setdefault(_primary(owner), {})
        cur.update({k: v for k, v in values.items() if v is not None})
        tmp = _prefs_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _prefs_path())
        return dict(cur)


def parse_answer(text):
    """Resposta curta de sim/não ('sim', 'faça', 'do it', 'manda bala'... / 'não', 'agora não'...). None = não é resposta."""
    t = (text or "").strip()
    if not t or len(t) > 60:
        return None
    if DENY_RE.match(t):
        return False
    if AFFIRM_RE.match(t):
        return True
    return None


def _keys(owner):
    """owner pode ser um nome ou vários (o administrador também é dono das conversas 'local', feitas no
    próprio PC sem login: assim ele continua as mesmas conversas logado pela rede ou em outra sessão)."""
    return tuple(owner) if isinstance(owner, (tuple, list, set)) else (owner,)


def _primary(owner):
    return _keys(owner)[0]


def _owns(conv, owner):
    return conv.get("owner") in _keys(owner)


def can_view(conv, owner, is_admin):
    return is_admin or _owns(conv, owner)


def can_edit(conv, owner):
    return _owns(conv, owner)


def create(owner, title="", preset="", model=""):
    with _lock:
        conv = {"id": secrets.token_hex(8), "owner": _primary(owner), "title": (title or "").strip()[:80] or "Nova conversa",
                "preset": preset or "", "model": model or "", "created": time.time(), "messages": [],
                "memory": "", "summarized_upto": 0, "compactions": 0,
                "anchors": [], "anchors_closed": False, "context_reset": False, "pins": [], "reset_id": 0}
        return _save(conv)


def get(cid, owner, is_admin):
    conv = _load(cid)
    if not can_view(conv, owner, is_admin):
        raise ConversationError("Conversa não encontrada.")
    return conv


def _chars(msgs):
    return sum(len(m.get("content") or "") for m in msgs)


def summary(conv):
    msgs = conv.get("messages", [])
    pending = msgs[conv.get("summarized_upto", 0):]
    return {"id": conv["id"], "owner": conv.get("owner", ""), "title": conv.get("title", ""),
            "preset": conv.get("preset", ""), "updated": conv.get("updated", 0), "created": conv.get("created", 0),
            "messages": len(msgs), "has_memory": bool(conv.get("memory")), "context_chars": _chars(pending),
            "anchors": len(conv.get("anchors") or []), "context_reset": bool(conv.get("context_reset")),
            "pins": len(conv.get("pins") or []), "can_undo": bool(conv.get("undo")),
            "compactions": conv.get("compactions", 0)}


def list_for(owner, is_admin, everyone=False):
    """Conversas do usuário (ou de todos, para administradores que pedirem), mais recentes primeiro."""
    out = []
    for name in os.listdir(_dir()):
        if not name.endswith(".json"):
            continue
        try:
            conv = _load(name[:-5])
        except ConversationError:
            continue
        if _owns(conv, owner) or (is_admin and everyone):
            out.append(summary(conv))
    out.sort(key=lambda c: c["updated"], reverse=True)
    return out


def _edit(cid, owner, fn):
    with _lock:
        conv = _load(cid)
        if not can_edit(conv, owner):
            raise ConversationError("Só o dono pode alterar esta conversa.")
        fn(conv)
        return _save(conv)


def rename(cid, owner, title):
    return _edit(cid, owner, lambda c: c.update(title=(title or "").strip()[:80] or c["title"]))


def set_memory(cid, owner, text):
    return _edit(cid, owner, lambda c: c.update(memory=(text or "").strip()[:MAX_MEMORY]))


def clear(cid, owner):
    """Limpeza: apaga mensagens e memória; a conversa continua existindo, vazia."""
    return _edit(cid, owner, lambda c: c.update(messages=[], memory="", summarized_upto=0, anchors=[],
                                                anchors_closed=False, context_reset=False, pins=[], undo=None,
                                                pending_question=None))


def delete(cid, owner, is_admin):
    with _lock:
        conv = _load(cid)
        if not (can_edit(conv, owner) or is_admin):
            raise ConversationError("Só o dono ou um administrador pode apagar esta conversa.")
        os.remove(_path(cid))


def cleanup(days, owner=None):
    """Apaga conversas paradas há mais de 'days' dias (de um dono ou de todos). Devolve quantas."""
    limit = time.time() - float(days) * 86400
    n = 0
    with _lock:
        for c in list_for(owner, True, everyone=owner is None):
            if c["updated"] < limit:
                os.remove(_path(c["id"]))
                n += 1
    return n


def append(cid, owner, role, content, display=None, meta=None, intent=None, keep=None):
    """intent: 'rescue' (reclamação de contexto: não vira âncora) ou 'reset' (vira o novo contexto).
    keep: na redefinição parcial, posições das âncoras antigas que continuam valendo."""
    def add(conv):
        msg = {"role": role, "content": content, "ts": time.time()}
        if display is not None and display != content:
            msg["display"] = display
        if meta:
            msg.update({k: v for k, v in meta.items() if v})
        conv["messages"].append(msg)
        if role == "user":
            _track_anchor(conv, len(conv["messages"]) - 1, display or content, intent, keep)
        if role == "user" and conv.get("title") in ("", "Nova conversa"):
            conv["title"] = re.sub(r"\s+", " ", display or content).strip()[:60] or "Nova conversa"
    return _edit(cid, owner, add)


def _track_anchor(conv, index, text, intent, keep=None):
    anchor = {"i": index, "text": (text or "").strip()[:ANCHOR_CHARS], "ts": time.time()}
    if intent == "reset":
        conv["undo"] = {"anchors": conv["anchors"], "anchors_closed": conv["anchors_closed"],
                        "context_reset": conv["context_reset"], "memory": conv.get("memory", ""), "msg": index}
        conv["reset_id"] = conv.get("reset_id", 0) + 1
        kept = [a for n, a in enumerate(conv["anchors"]) if keep and n in keep]
        conv["anchors"] = kept + [anchor]
        conv["anchors_closed"] = True  # o contexto vigente é só o que o usuário declarou (o resto: 📌 fixar)
        conv["context_reset"] = True
        return
    if intent in ("rescue", "skip") or conv.get("anchors_closed"):
        return
    anchors = conv["anchors"]
    if len(anchors) < ANCHOR_MIN or (len(anchors) < ANCHOR_MAX and _related(text, anchors)):
        anchors.append(anchor)
    else:
        conv["anchors_closed"] = True  # o assunto de abertura terminou: para de capturar


def undo_reset(cid, owner):
    """Desfaz a última redefinição de contexto (âncoras, memória e marcações voltam como estavam)."""
    def undo(conv):
        u = conv.get("undo")
        if not u:
            raise ConversationError("Não há redefinição para desfazer.")
        conv.update(anchors=u["anchors"], anchors_closed=u["anchors_closed"], context_reset=u["context_reset"],
                    memory=u["memory"], undo=None)
        conv["reset_id"] = conv.get("reset_id", 0) + 1  # invalida a reescrita de memória em andamento
    return _edit(cid, owner, undo)


def toggle_pin(cid, owner, index):
    """Fixa/desafixa uma mensagem: fixadas vão em toda resposta, mesmo depois de compactar."""
    def tog(conv):
        if not 0 <= index < len(conv["messages"]):
            raise ConversationError("Mensagem não encontrada.")
        pins = conv["pins"]
        if index in pins:
            pins.remove(index)
        else:
            pins.append(index)
            pins.sort()
    return _edit(cid, owner, tog)


def set_pending_question(cid, owner, value):
    return _edit(cid, owner, lambda c: c.update(pending_question=value))


def remove_anchor(cid, owner, index):
    """Tira uma âncora (pela posição na lista)."""
    def rm(conv):
        if 0 <= index < len(conv["anchors"]):
            conv["anchors"].pop(index)
    return _edit(cid, owner, rm)


def pop_last_user(cid, owner):
    """Desfaz a última pergunta (quando o pedido falhou ou foi cancelado antes da resposta)."""
    def undo(conv):
        if conv["messages"] and conv["messages"][-1]["role"] == "user":
            last = len(conv["messages"]) - 1
            conv["anchors"] = [a for a in conv["anchors"] if a["i"] != last]
            conv["pins"] = [i for i in conv["pins"] if i != last]
            if (conv.get("undo") or {}).get("msg") == last:  # a redefinição era dessa pergunta: volta atrás
                u = conv["undo"]
                conv.update(anchors=u["anchors"], anchors_closed=u["anchors_closed"],
                            context_reset=u["context_reset"], memory=u["memory"], undo=None)
            conv["messages"].pop()
            conv["summarized_upto"] = min(conv["summarized_upto"], len(conv["messages"]))
    return _edit(cid, owner, undo)


def _anchor_block(conv):
    return "\n".join(f"{n}. {a['text']}" for n, a in enumerate(conv["anchors"], 1))


def _snippet_block(conv, indexes):
    out = []
    for i in indexes:
        m = conv["messages"][i]
        who = "USUÁRIO" if m["role"] == "user" else "ASSISTENTE"
        out.append(f"[mensagem {i + 1}, {who}]\n{(m.get('content') or '')[:1500]}")
    return "\n\n".join(out)


def build_context(conv, system_prompt, budget=CONTEXT_BUDGET, intent=None, query=""):
    """Mensagens para o modelo: instrução + contexto vigente/resgate + memória + as mais recentes no orçamento.
    Devolve só a lista de mensagens (o que foi resgatado fica em conv['_last_rescue'] para o painel avisar)."""
    system = system_prompt or ""
    pending_start = conv.get("summarized_upto", 0)
    pending = conv["messages"][pending_start:]
    recent, used, first_recent = [], 0, len(conv["messages"])
    for k, m in enumerate(reversed(pending)):
        size = len(m.get("content") or "")
        if recent and used + size > budget:
            break
        recent.append({"role": m["role"], "content": m["content"]})
        used += size
        first_recent = len(conv["messages"]) - 1 - k
    recent.reverse()
    in_context = set(range(first_recent, len(conv["messages"])))
    anchor_idx = {a["i"] for a in conv["anchors"]}
    rescued = []

    if conv.get("context_reset") and conv["anchors"]:
        system += ("\n\nCONTEXTO VIGENTE DESTA CONVERSA (o usuário redefiniu o contexto; o que ele disse antes e "
                   "conflite com isto NÃO vale mais):\n" + _anchor_block(conv))
    if intent == "reset":
        words = _words(query)
        rescued = _relevant_messages(conv, words, in_context | anchor_idx)
        system += ("\n\nO USUÁRIO ACABOU DE DIZER QUE O CONTEXTO MUDOU. Confirme em uma frase o contexto novo como "
                   "você entendeu, descarte o que pertencia ao antigo e trabalhe a partir do novo. Se faltar alguma "
                   "informação para reintegrar o que já foi feito, peça para ele dizer.")
        if rescued:
            system += ("\n\nTRECHOS DA CONVERSA QUE SE LIGAM AO NOVO CONTEXTO (reaproveite o que ainda servir):\n"
                       + _snippet_block(conv, rescued))
    elif intent == "rescue":
        words = _words(query).union(*(_words(a["text"]) for a in conv["anchors"]))
        rescued = _relevant_messages(conv, words, in_context | anchor_idx)
        system += ("\n\nO USUÁRIO RECLAMOU DE PERDA DE CONTEXTO. Retome o que foi pedido no início da conversa "
                   "(abaixo), reconheça em uma frase o que tinha ficado de fora e continue a partir daí.")
        if conv["anchors"] and not conv.get("context_reset"):
            system += "\n\nPEDIDOS INICIAIS DA CONVERSA (contexto original):\n" + _anchor_block(conv)
        if rescued:
            system += "\n\nTRECHOS ANTIGOS DA CONVERSA SOBRE O ASSUNTO:\n" + _snippet_block(conv, rescued)
    conv["_last_rescue"] = {"intent": intent, "anchors": len(conv["anchors"]), "snippets": len(rescued)}

    pinned = [i for i in conv.get("pins", []) if i not in in_context and i < len(conv["messages"])]
    if pinned:
        block, used_pins = [], 0
        for i in pinned:
            m = conv["messages"][i]
            text = (m.get("content") or "")[:3000]
            if used_pins + len(text) > PIN_BUDGET:
                break
            used_pins += len(text)
            block.append(f"[{'USUÁRIO' if m['role'] == 'user' else 'ASSISTENTE'}] {text}")
        system += ("\n\nMENSAGENS FIXADAS PELO USUÁRIO (importantes: continuam valendo):\n" + "\n\n".join(block))
    if conv.get("memory"):
        system += ("\n\nMEMÓRIA DESTA CONVERSA (resumo do que já foi falado; use como contexto, não repita):\n"
                   + conv["memory"])
    while recent and recent[0]["role"] == "assistant":  # o contexto começa sempre por uma pergunta
        recent.pop(0)
    return [{"role": "system", "content": system}] + recent


def needs_compaction(conv):
    return _chars(conv["messages"][conv.get("summarized_upto", 0):]) > AUTO_COMPACT_AT


INTENT_SYSTEM = (
    "Classifique a ÚLTIMA mensagem do usuário numa conversa com um assistente. Responda SÓ JSON: "
    '{"intent": "reset" | "rescue" | "none"}. '
    "reset = o usuário diz que o contexto/objetivo/plano DA CONVERSA mudou e o anterior não vale mais. "
    "rescue = o usuário reclama que o assistente esqueceu ou perdeu o contexto do que foi dito antes. "
    "none = qualquer outra coisa, INCLUSIVE quando a frase é texto criativo, fala de personagem, citação, "
    "diálogo de NPC ou exemplo pedido pelo usuário."
)
PARTIAL_SYSTEM = (
    "O usuário redefiniu parte do contexto de uma conversa. Você recebe os ITENS DO CONTEXTO ATUAL numerados e a "
    "MENSAGEM NOVA. Decida quais itens continuam valendo (não conflitam com a mensagem nova). Responda SÓ JSON: "
    '{"keep": [números dos itens que continuam], "removed": [números dos itens que deixam de valer]}. '
    "Na dúvida, mantenha o item."
)


def _ask_json_text(ask, system, user):
    raw = _ask_or_default(ask)({"model": "auto", "max_tokens": 300, "temperature": 0, "messages": [
        {"role": "system", "content": system}, {"role": "user", "content": user}]})
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        raise ConversationError("A IA não respondeu no formato esperado.")
    return json.loads(m.group(0))


def confirm_intent(conv, text, intent, ask=None):
    """Opcional (gasta 1 consulta): a IA confirma se a frase era mesmo reset/rescue. Devolve a intenção final."""
    last = next((m.get("content", "")[:800] for m in reversed(conv["messages"]) if m["role"] == "assistant"), "")
    try:
        data = _ask_json_text(ask, INTENT_SYSTEM, f"MODO: {conv.get('preset') or 'livre'}\n"
                                                  f"ÚLTIMA RESPOSTA DO ASSISTENTE:\n{last}\n\n"
                                                  f"MENSAGEM DO USUÁRIO:\n{text[:1500]}")
    except (ConversationError, ValueError):
        return intent  # sem resposta da IA: fica a detecção por frase
    got = str(data.get("intent") or "").lower()
    return got if got in ("reset", "rescue") else None


def partial_keep(conv, text, ask=None):
    """Opcional (gasta 1 consulta): quais âncoras antigas continuam valendo. Devolve (keep, textos_removidos)."""
    anchors = conv.get("anchors") or []
    if not anchors:
        return [], []
    items = "\n".join(f"{n}. {a['text'][:600]}" for n, a in enumerate(anchors, 1))
    try:
        data = _ask_json_text(ask, PARTIAL_SYSTEM, f"ITENS DO CONTEXTO ATUAL:\n{items}\n\nMENSAGEM NOVA:\n{text[:1500]}")
        keep = sorted({int(n) - 1 for n in data.get("keep") or [] if 1 <= int(n) <= len(anchors)})
    except (ConversationError, ValueError, TypeError):
        return [], [a["text"] for a in anchors]  # sem resposta: troca tudo (comportamento padrão)
    removed = [a["text"] for n, a in enumerate(anchors) if n not in keep]
    return keep, removed


REBASE_SYSTEM = (
    "Você mantém a MEMÓRIA de uma conversa. O usuário acabou de REDEFINIR o contexto. Reescreva a memória em "
    "português do Brasil, em tópicos curtos: mantenha só o que continua valendo no contexto novo, retire o que "
    "pertencia ao contexto antigo e conflita com o novo, e comece com uma linha 'Contexto atual: ...'. "
    "Não invente nada. Responda SÓ com a memória."
)


def rebase_memory(cid, owner, ask=None):
    """Depois de uma redefinição de contexto: reescreve a memória sem o que ficou obsoleto."""
    conv = _load(cid)
    if not can_edit(conv, owner) or not conv.get("memory") or not conv["anchors"]:
        return None
    payload = {"model": "auto", "max_tokens": 2500, "temperature": 0.2, "messages": [
        {"role": "system", "content": REBASE_SYSTEM},
        {"role": "user", "content": f"CONTEXTO NOVO (palavras do usuário):\n{_anchor_block(conv)}\n\n"
                                    f"MEMÓRIA ATUAL:\n{conv['memory']}"}]}
    rid = conv.get("reset_id", 0)
    memory = (_ask_or_default(ask)(payload) or "").strip()
    if memory:
        def apply(c):
            if c.get("reset_id", 0) == rid:  # desfeita no meio? então não mexe
                c["memory"] = memory[:MAX_MEMORY]
        conv = _edit(cid, owner, apply)
    return conv["memory"]


def _ask_or_default(ask):
    if ask is not None:
        return ask

    def default(p):
        try:
            data, _ = router.chat_completion(p, timeout=120)
        except router.RouterError as e:
            raise ConversationError(f"Não deu para falar com a IA agora: {e}")
        return ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    return default


def compact(cid, owner, model=None, ask=None):
    """Resume na memória as mensagens ainda fora dela (menos as últimas KEEP_RECENT).
    ask(payload) -> texto: injetável nos testes; por padrão usa o rodízio de provedores."""
    conv = _load(cid)
    if not can_edit(conv, owner):
        raise ConversationError("Só o dono pode compactar esta conversa.")
    start = conv.get("summarized_upto", 0)
    end = max(start, len(conv["messages"]) - KEEP_RECENT)
    if end <= start:
        raise ConversationError("Nada para compactar ainda: a conversa é curta.")
    chunk = conv["messages"][start:end]
    transcript = "\n\n".join(f"[{'USUÁRIO' if m['role'] == 'user' else 'ASSISTENTE'}]\n{m['content'][:6000]}"
                             for m in chunk)
    payload = {"model": model or "auto", "max_tokens": 2500, "temperature": 0.2, "messages": [
        {"role": "system", "content": COMPACT_SYSTEM},
        {"role": "user", "content": f"MEMÓRIA ATUAL:\n{conv.get('memory') or '(vazia)'}\n\nMENSAGENS NOVAS:\n{transcript}"}]}
    memory = (_ask_or_default(ask)(payload) or "").strip()
    if not memory:
        raise ConversationError("O modelo não devolveu a memória; tente de novo.")

    def apply(c):
        if c.get("summarized_upto", 0) != start:  # outra compactação aconteceu no meio
            raise ConversationError("A conversa mudou durante a compactação; tente de novo.")
        c["memory"] = memory[:MAX_MEMORY]
        c["summarized_upto"] = end
        c["compactions"] = c.get("compactions", 0) + 1
    conv = _edit(cid, owner, apply)
    return {"memory": conv["memory"], "summarized": end - start}
