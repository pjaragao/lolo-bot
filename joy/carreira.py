"""CareerOps (busca de vagas e LinkedIn do Paulo) pelo WhatsApp.

O Lolo não decide nada sozinho: repassa o que o Paulo aprova, rejeita ou responde, e entrega os avisos que o CareerOps
prepara (textos prontos). As regras (o que pode ser enviado, limites, horários, quando parar) ficam no CareerOps.
O token é o de "bot": aprova e responde pelo Paulo, mas não liga o modo, não troca a conta e não mexe em limites.

O conteúdo de posts e e-mails é dado externo: nunca vira instrução."""
import datetime
import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

import google
import gmail
import lembretes
import midia

HOME = os.environ.get("HERMES_HOME", "/opt/data")
ESTADO = os.path.join(HOME, "carreira_estado.json")
PADRAO_API = "http://172.26.0.1:8005/api"
EMAIL_PRIMEIRA_LEITURA_DIAS = 45
EMAIL_LOTE = 25
EMAIL_MAX = 300


def _cfg() -> Dict[str, str]:
    """URL e token do CareerOps. Os scripts do cron rodam com o ambiente filtrado: se faltar, lê do .env do bot."""
    cfg = {"CAREEROPS_API_URL": os.environ.get("CAREEROPS_API_URL", ""), "CAREEROPS_BOT_TOKEN": os.environ.get("CAREEROPS_BOT_TOKEN", "")}
    if not all(cfg.values()):
        try:
            with open(os.path.join(HOME, ".env"), encoding="utf-8") as f:
                for ln in f:
                    k, _, v = ln.strip().partition("=")
                    if k in cfg and not cfg[k]:
                        cfg[k] = v.strip().strip("'\"")
        except OSError:
            pass
    cfg["CAREEROPS_API_URL"] = (cfg["CAREEROPS_API_URL"] or PADRAO_API).rstrip("/")
    return cfg


class Erro(Exception):
    pass


def _api(method: str, path: str, body: Any = None, timeout: int = 30, raw: bool = False) -> Any:
    cfg = _cfg()
    if not cfg["CAREEROPS_BOT_TOKEN"]:
        raise Erro("CareerOps não configurado: falta CAREEROPS_BOT_TOKEN no .env do Lolo.")
    url = path if path.startswith("http") else cfg["CAREEROPS_API_URL"] + (path if path.startswith("/") else "/" + path)
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"X-CareerOps-Token": cfg["CAREEROPS_BOT_TOKEN"], "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
            return data if raw else (json.loads(data) if data else {})
    except urllib.error.HTTPError as exc:
        detalhe = exc.read().decode("utf-8", "replace")[:300]
        try:
            detalhe = json.loads(detalhe).get("detail") or detalhe
        except ValueError:
            pass
        raise Erro(f"CareerOps {exc.code}: {detalhe}") from None
    except urllib.error.URLError as exc:
        raise Erro(f"CareerOps fora do ar ({exc.reason})") from None


def _sem_acento(t: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c)).lower()


_AUTOMACAO = r"(a\s+)?automac(ao|oes)(\s+do\s+linkedin)?"
_TIPO = r"(vagas?|comentarios?|conexoes|conexao|convites?|seguir)"
_IDS = r"#?\d+(\s*(,|e)?\s*#?\d+)*"
_TENTAR = r"(tentar|tenta|tente|tentar\s+de\s+novo|tenta\s+de\s+novo|tente\s+de\s+novo|tentar\s+novamente|tenta\s+novamente|refazer|refaz|refaca)"

COMANDOS = [
    (re.compile(rf"^(religar|religa|religue|ligar|liga|retomar|retoma|voltar)\s+{_AUTOMACAO}$"), lambda m: ("carreira_religar", {})),
    (re.compile(rf"^(parar|pare|para|pausar|pausa)\s+{_AUTOMACAO}(\s*[:,-]?\s*(?P<motivo>.+))?$"),
     lambda m: ("carreira_parar", {"texto": m.group("motivo") or ""})),
    (re.compile(rf"^(aprovar|aprova|aprove)\s+(todas?|todos?)\s+(as\s+|os\s+)?(?P<tipo>{_TIPO})(?P<agora>\s+(agora|ja))?$"),
     lambda m: ("carreira_aprovar", {"alvo": m.group("tipo"), "agora": bool(m.group("agora"))})),
    (re.compile(r"^(aprovar|aprova|aprove|ok|pode)\s+(?P<ids>#?\d+(\s*(,|e)?\s*#?\d+)*)(?P<agora>\s+(agora|ja))?$"),
     lambda m: ("carreira_aprovar", {"ids": m.group("ids"), "agora": bool(m.group("agora"))})),
    (re.compile(r"^(rejeitar|rejeita|rejeite|recusar|recusa)\s+(?P<ids>#?\d+(\s*(,|e)?\s*#?\d+)*)$"),
     lambda m: ("carreira_rejeitar", {"ids": m.group("ids")})),
    # what the "Precisa de você" / "Pronto para enviar" / CV notices tell him to say
    (re.compile(rf"^{_TENTAR}\s+(?P<ids>{_IDS})$"), lambda m: ("carreira_tentar", {"ids": m.group("ids")})),
    (re.compile(rf"^(cancelar|cancela|cancele|desistir)\s+(?P<ids>{_IDS})$"), lambda m: ("carreira_cancelar", {"ids": m.group("ids")})),
    (re.compile(rf"^pode\s+(enviar|ir|mandar)\s+(?P<ids>{_IDS})$"), lambda m: ("carreira_cv_ok", {"ids": m.group("ids")})),
    (re.compile(rf"^(confirmar|confirma|confirme|confirmo|enviar|envia|envie)\s+(?P<ids>{_IDS})$"),
     lambda m: ("carreira_confirmar", {"ids": m.group("ids")})),
    (re.compile(r"^(quais\s+(foram|sao)\s+)?(as\s+|os\s+)?(ultim[oa]s|recentes)\s+(?P<o>postagens|posts|publicacoes|comentarios|acoes)"
                r"(\s+(no|do)\s+linkedin)?(\s+(feit[oa]s|postad[oa]s|publicad[oa]s))?$"),
     lambda m: ("carreira_feitos", {"alvo": "comentarios" if m.group("o") in ("postagens", "posts", "publicacoes", "comentarios") else ""})),
    (re.compile(r"^(importar|importa|importe|puxar|puxa|puxe|buscar|busca|busque|atualizar|atualiza|atualize|sincronizar|sincroniza|"
                r"sincronize|trazer|traz|traga|ler|le|leia)\s+(as\s+)?(minhas\s+)?vagas\s+salvas(\s+(do|no)\s+linkedin)?(\s+(agora|ja))?$"),
     lambda m: ("carreira_vagas_salvas", {})),
    (re.compile(r"^fila(\s+autorizada)?$|^(o\s+que\s+)?(esta|ta)\s+autorizado$"), lambda m: ("carreira_fila", {})),
    (re.compile(r"^(para|pra)\s+aprovar$|^pendentes$|^o\s+que\s+(falta|tem\s+para|tem\s+pra)\s+aprovar$"), lambda m: ("carreira_pendentes", {})),
    # the short summary on request (2026-11-05): "5 vagas, 3 comentários e 1 conexão" and the link
    (re.compile(r"^(resumo|novidades|atualiza[cç][aã]o)(\s+(do\s+|da\s+)?(careerops|carreira|linkedin|automa[cç][aã]o))?$|^(careerops|carreira)$"),
     lambda m: ("carreira_resumo", {})),
]


# the address Google sends back after the reconnection link (google.avisar_reconexao): http://localhost:1/?...code=...
GOOGLE_VOLTA = re.compile(r"^(https?://)?localhost:1/?\?\S*\bcode=\S+$", re.I)

LINK_POST = re.compile(r"(?:https?://)?(?:www\.)?(?:lnkd\.in/[\w/-]+|linkedin\.com/(?:posts|feed/update|pulse)/[^\s<>\"']+)", re.I)
# what is left around a link that is only a request to comment, not his opinion on the post
_PEDIDO = re.compile(r"\b(comenta|comentar|comente|comentario|isso|esse|este|post|postagem|link|links|adicion[ae]|adicionar|coloc[ae]|colocar|"
                     r"ao|no|na|sistema|careerops|fila|para|pra|por|favor|pfv|pf|integre|integra|salv[ae]|salvei|tinha|havia|"
                     r"esses|estes|aqui|e|o|a|os|as|de|do|da|um|uma)\b|[:•\-–,.;!?]", re.I)


def _links_de_post(texto: str) -> Tuple[List[str], str]:
    """(links de post do LinkedIn na mensagem, sem repetir; o resto do texto)"""
    achados = []
    for m in LINK_POST.finditer(texto or ""):
        url = m.group(0).rstrip(".,);")
        url = url if url.lower().startswith("http") else "https://" + url
        if url not in achados:
            achados.append(url)
    return achados, LINK_POST.sub(" ", texto or "")


def comentar_links(urls: List[str], sugestao: str = "") -> str:
    """Vários posts de uma vez: um rascunho para cada, cada um esperando o seu OK."""
    saidas = []
    for url in urls[:15]:
        try:
            saidas.append(comentar_link(url, sugestao if len(urls) == 1 else ""))
        except Erro as exc:
            saidas.append(f"⚠️ {url}: {_motivo(exc)}")
    return "\n\n".join(saidas)


# --------------------------------------------------------------------------- respostas por "reply"
# Each message Lolo sends about a CareerOps item is stored (WhatsApp message id → what it is about), so a reply
# to it ("ok", "não", "ok 1 3", "mais curto") needs no number. Old messages that still show "#12" keep working.
REFS_DIAS = 14
_PENDENTES: Dict[str, Dict[str, Any]] = {}   # text about to be sent by the adapter → its reference


def _refs_db():
    import sqlite3
    home = os.environ.get("HERMES_HOME") or "/opt/data"
    os.makedirs(os.path.join(home, "cache"), exist_ok=True)
    con = sqlite3.connect(os.path.join(home, "cache", "carreira_refs.db"), timeout=5)
    con.execute("CREATE TABLE IF NOT EXISTS refs (msg_id TEXT PRIMARY KEY, ref TEXT, ts REAL)")
    return con


def guardar_ref(msg_id: str, ref: Optional[Dict[str, Any]]) -> None:
    if not msg_id or not ref:
        return
    import time
    with _refs_db() as con:
        con.execute("INSERT OR REPLACE INTO refs VALUES (?,?,?)", (msg_id, json.dumps(ref), time.time()))
        con.execute("DELETE FROM refs WHERE ts < ?", (time.time() - REFS_DIAS * 86400,))


def ref_de(msg_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """What the message he replied to is about (None for any other message)."""
    if not msg_id:
        return None
    try:
        with _refs_db() as con:
            row = con.execute("SELECT ref FROM refs WHERE msg_id = ?", (msg_id,)).fetchone()
        return json.loads(row[0]) if row else None
    except Exception:
        return None


def _com_ref(texto: str, ref: Dict[str, Any]) -> str:
    """The answer the adapter is about to send carries this reference (looked up by its exact text)."""
    if len(_PENDENTES) > 50:
        _PENDENTES.clear()
    _PENDENTES[texto] = ref
    return texto


def ref_pendente(texto: str) -> Optional[Dict[str, Any]]:
    return _PENDENTES.pop(texto or "", None)


RASCUNHO_CITADO = re.compile(r"(?:Rascunho|Revisado) #(\d+)")
AVISO_CITADO = re.compile(r"(?P<tipo>Precisa de você|Pronto para enviar|CV para revisar|O revisor não aprovou o CV)\*?\s*#(?P<id>\d+)")
_AVISO_TIPO = {"Precisa de você": "needs_user", "Pronto para enviar": "awaiting_confirm",
               "CV para revisar": "review_docs", "O revisor não aprovou o CV": "review_docs"}
_DE_NOVO = re.compile(rf"^({_TENTAR}|de novo|novamente|tenta ai|tenta de novo ai)$")
_SIM = (r"ok|okay|okk|oks|s|sim|ss|pode|pode sim|sim pode|ok pode|pode ir|pode enviar|pode mandar|pode publicar|manda|manda ver|"
        r"vai|bora|beleza|blz|show|perfeito|otimo|fechado|certo|isso|aprovo|aprovar?|aprove|aprovado|publica|publicar|confirmo|"
        r"confirmar?|confirme|enviar?|envie|👍|✅|👌")
_NEGA = r"nao|n|nn|nope|negativo|nao quero|melhor nao|nao obrigado|rejeitar?|rejeite|recusar?|descarta|descartar|pula|pular|" \
        r"cancelar?|cancele|desistir|desiste|deixa|deixa pra la|❌|👎"
_OK = re.compile(rf"^({_SIM})(\s+(?P<agora>agora|ja))?$")
_NAO = re.compile(rf"^({_NEGA})$")
# a numbered list: "ok", "ok 1 3", "1 e 3", "ok agora", "ok menos 2", "não 2"
_LISTA_OK = re.compile(rf"^(({_SIM})\s*)?(?P<n>\d+([\s,e]+\d+)*)?(\s+(?P<agora>agora|ja))?$")
_LISTA_MENOS = re.compile(rf"^(({_SIM})\s+)?(todas?|todos?\s+)?(menos|exceto|tirando|sem)\s+(?P<n>\d+([\s,e]+\d+)*)(\s+(?P<agora>agora|ja))?$")
_LISTA_NAO = re.compile(rf"^({_NEGA})(\s+(?P<n>\d+([\s,e]+\d+)*))?$")
# kinds of comment (CareerOps COMMENT_ANGLES): a reply with only the word rewrites the draft in that kind
ANGULOS = {"tecnico": "tecnico", "tecnica": "tecnico", "mais tecnico": "tecnico", "elogio": "elogio", "elogia": "elogio",
           "elogie": "elogio", "elogiar": "elogio", "pergunta": "pergunta", "pergunte": "pergunta", "perguntar": "pergunta",
           "contraponto": "contraponto", "discorde": "contraponto", "discordar": "contraponto", "complemento": "complemento",
           "complemente": "complemento", "complementar": "complemento", "experiencia": "experiencia",
           "minha experiencia": "experiencia", "cite minha experiencia": "experiencia"}
_TEXTO_FINAL = re.compile(r"^\s*texto(\s+final)?\s*:\s*(?P<t>.+)$", re.I | re.S)
_REVISAR = re.compile(r"^\s*(revis[ae]r?|ajust[ae]r?|reescrev\w*)\s+#?(?P<id>\d+)\s*[:,-]?\s*(?P<p>.+)$", re.I | re.S)


def _curto(texto: str) -> str:
    return re.sub(r"[?!.]+$", "", " ".join(_sem_acento(texto).split())).strip()


def _posicoes(n: Optional[str], ids: List[int]) -> Optional[List[int]]:
    """'1 3' → the ids on lines 1 and 3; None when a number is not on the list."""
    pos = [int(x) for x in re.findall(r"\d+", n or "")]
    if any(p < 1 or p > len(ids) for p in pos):
        return None
    return [ids[p - 1] for p in dict.fromkeys(pos)]


def _fora(ids: List[int]) -> Tuple[str, Dict[str, Any]]:
    """A number that is not on the list he replied to: say so, never read it as an item id."""
    return ("carreira_fora_da_lista", {"total": len(ids)})


def fora_da_lista(total: Any) -> str:
    return f"Essa lista tem {total} item(ns): responda com os números de 1 a {total} (ex.: “ok 1 3”, “não 2”)."


def _citado_ref(citado: str) -> Optional[Dict[str, Any]]:
    """Old messages, with the number in the text."""
    alvo = RASCUNHO_CITADO.search(citado or "")
    if alvo:
        return {"tipo": "rascunho", "ids": [int(alvo.group(1))]}
    aviso = AVISO_CITADO.search(citado or "")
    if aviso:
        return {"tipo": _AVISO_TIPO[aviso.group("tipo")], "ids": [int(aviso.group("id"))],
                "error_code": "confirm_timeout" if "confirmar #" in citado else None}
    return None


def _resposta(texto: str, ref: Dict[str, Any]) -> Optional[Tuple[str, Dict[str, Any]]]:
    ids = [int(i) for i in ref.get("ids") or []]
    if not ids or not (texto or "").strip():
        return None
    curto, tipo = _curto(texto), ref.get("tipo")
    um = str(ids[0])
    if tipo == "rascunho":   # ok / no / a kind of comment / your own text / anything else is a request for the AI
        m = _OK.match(curto)
        if m:
            return ("carreira_aprovar", {"ids": um, "agora": bool(m.group("agora"))})
        if _NAO.match(curto):
            return ("carreira_rejeitar", {"ids": um})
        if curto in ANGULOS:
            return ("carreira_revisar", {"ids": um, "texto": "", "angulo": ANGULOS[curto]})
        final = _TEXTO_FINAL.match(texto)
        if final:
            return ("carreira_aprovar", {"ids": um, "texto": final.group("t").strip()})
        if not _links_de_post(texto)[0]:
            return ("carreira_revisar", {"ids": um, "texto": texto.strip()})
        return None
    if tipo == "list":
        m = _LISTA_MENOS.match(curto)
        if m:
            fora = _posicoes(m.group("n"), ids)
            if fora is None:
                return _fora(ids)
            resto = [i for i in ids if i not in fora]
            return ("carreira_aprovar", {"ids": " ".join(map(str, resto)), "agora": bool(m.group("agora"))}) if resto else None
        m = _LISTA_NAO.match(curto)
        if m:
            alvo = _posicoes(m.group("n"), ids) if m.group("n") else ids
            return ("carreira_rejeitar", {"ids": " ".join(map(str, alvo))}) if alvo else _fora(ids)
        m = _LISTA_OK.match(curto)
        if m and (m.group(2) or m.group("n")):
            alvo = _posicoes(m.group("n"), ids) if m.group("n") else ids
            return ("carreira_aprovar", {"ids": " ".join(map(str, alvo)), "agora": bool(m.group("agora"))}) if alvo else _fora(ids)
        return None
    # a notice about one item
    if _NAO.match(curto):
        return ("carreira_cancelar", {"ids": um})
    if _DE_NOVO.match(curto):
        return ("carreira_tentar", {"ids": um})
    if _OK.match(curto):
        if tipo == "review_docs":
            return ("carreira_cv_ok", {"ids": um})
        if tipo == "awaiting_confirm" or ref.get("error_code") == "confirm_timeout":
            return ("carreira_confirmar", {"ids": um})
        return ("carreira_tentar", {"ids": um})
    if "=" in texto and tipo == "needs_user":   # answers to the form's questions
        return ("carreira_responder", {"ids": um, "texto": texto.strip()})
    return None


def comando(texto: str, citado: str = "", ref: Optional[Dict[str, Any]] = None) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Os comandos fixos da automação, sem passar pelo modelo: (consulta, args) ou None.
    Só o texto inteiro conta: uma frase maior ou diferente fica com o modelo.
    ref = o que a mensagem respondida (reply) é; sem ele, o número no texto citado (mensagens antigas).
    Link de post do LinkedIn = comentar (o texto em volta vira a sugestão, se for uma opinião e não só o pedido)."""
    if GOOGLE_VOLTA.match((texto or "").strip()):
        return ("carreira_google", {"endereco": texto.strip()})
    m = _REVISAR.match(texto or "")
    if m:
        return ("carreira_revisar", {"ids": m.group("id"), "texto": m.group("p").strip()})
    ref = ref or _citado_ref(citado)
    if ref:
        r = _resposta(texto, ref)
        if r:
            return r
    links, resto = _links_de_post(texto)
    if links:
        opiniao = " ".join(resto.split())
        sobra = _PEDIDO.sub(" ", _sem_acento(opiniao)).split()
        return ("carreira_comentar_varios", {"urls": links, "sugestao": opiniao if len(links) == 1 and len(sobra) >= 3 else ""})
    t = re.sub(r"[?!.]+$", "", re.sub(r"\s+", " ", _sem_acento(texto or "").strip())).strip()
    for rx, fazer in COMANDOS:
        m = rx.match(t)
        if m:
            return fazer(m)
    return None


def _ids(v: Any) -> List[int]:
    """'12 15', '#12,#15', [12, '15'] → [12, 15]."""
    if v is None:
        return []
    if not isinstance(v, (list, tuple)):
        v = [v]
    out = []
    for x in v:
        out += [int(n) for n in re.findall(r"\d+", str(x))]
    return list(dict.fromkeys(out))


# --------------------------------------------------------------------------- consultas (ferramenta lolo)
def visao() -> str:
    return _api("GET", "/automation/bot/overview")["text"]


def resumo() -> str:
    """O resumo curto do CareerOps: quanto espera por você e o link. O mesmo do bom dia e das atualizações de 30 em 30 min."""
    return _api("GET", "/automation/bot/summary")["text"]


def pendentes() -> str:
    caixa = _api("GET", "/automation/bot/inbox")
    partes = [caixa["text"]]
    itens = _api("GET", "/automation/needs-user").get("items") or []
    if itens:
        rotulo = {"needs_user": "precisa de resposta", "review_docs": "CV para revisar", "awaiting_confirm": "pronto para o clique final"}
        partes.append("\n🙋 *Precisa de você*")
        partes += [f"#{a['id']} {a.get('title') or ''} — {rotulo.get(a['status'], a['status'])}"
                   + (f": {a['error_text']}" if a.get("error_text") and a["status"] == "needs_user" else "") for a in itens[:15]]
    texto = "\n".join(partes)
    return _com_ref(texto, {"tipo": "list", "ids": caixa.get("ids") or []}) if caixa.get("ids") else texto


TIPOS = {"vaga": "apply", "vagas": "apply", "candidatura": "apply", "candidaturas": "apply", "comentario": "comment",
         "comentarios": "comment", "comentário": "comment", "comentários": "comment", "conexao": "connect", "conexoes": "connect",
         "conexão": "connect", "conexões": "connect", "convite": "connect", "convites": "connect", "seguir": "follow"}


ROTULO_FEITO = {"comment": "💬", "apply": "📨", "connect": "🤝", "follow": "➕"}


def _quando(iso: Optional[str]) -> str:
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.fromisoformat(str(iso)).astimezone(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m %H:%M")
    except (TypeError, ValueError):
        return ""


NOME_TIPO = {"comment": ("comentário", "comentários"), "apply": ("vaga", "vagas"), "connect": ("conexão", "conexões"),
             "follow": ("seguir", "seguir")}


def _por_tipo(itens: List[Dict[str, Any]]) -> str:
    conta: Dict[str, int] = {}
    for a in itens:
        conta[a.get("kind")] = conta.get(a.get("kind"), 0) + 1
    return ", ".join(f"{n} {NOME_TIPO.get(k, (k, k))[0 if n == 1 else 1]}" for k, n in sorted(conta.items(), key=lambda x: -x[1]))


def _titulo(a: Dict[str, Any]) -> str:
    p = a.get("payload") or {}
    if a.get("kind") == "comment":
        cabeca = next((l.strip() for l in (p.get("post_head") or "").splitlines() if l.strip()), "")
        cabeca = cabeca if len(cabeca) <= 90 else cabeca[:87] + "…"
        return f"Post de {p.get('author') or a.get('title') or '—'}" + (f": {cabeca}" if cabeca else "")
    if a.get("kind") == "apply":
        return p.get("title") or a.get("title") or "Vaga"
    return p.get("name") or a.get("title") or ""


def _fila() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(aprovados esperando para executar, esperando a aprovação do Paulo)"""
    try:
        autorizados = [a for a in _api("GET", "/automation/running").get("items") or [] if a.get("status") in ("approved", "queued", "review_docs")]
    except Erro:
        autorizados = []
    return autorizados, _api("GET", "/automation/inbox").get("items") or []


def feitos(tipo: str = "", n: Any = None) -> str:
    """O que o sistema já executou no LinkedIn, do mais recente: título do post, comentário e link para acompanhar.
    Termina perguntando se ele quer ver a fila, com as quantidades."""
    kind = TIPOS.get((tipo or "").lower().strip())
    try:
        limite = max(1, min(int(n or 5), 30))
    except (TypeError, ValueError):
        limite = 5
    itens = [a for a in _api("GET", "/automation/history").get("items") or []
             if a.get("status") == "done" and (not kind or a.get("kind") == kind)][:limite]
    linhas = [f"✅ *Feitos no LinkedIn* (últimos {len(itens)})" if itens else "Nada executado ainda" + (f" em {tipo}." if kind else ".")]
    for a in itens:
        p = a.get("payload") or {}
        linhas.append(f"\n{ROTULO_FEITO.get(a.get('kind'), '•')} #{a['id']} · {_quando(a.get('finished_at'))}\n*{_titulo(a)}*")
        if a.get("kind") == "comment" and p.get("text"):
            texto = p["text"] if len(p["text"]) <= 280 else p["text"][:277] + "…"
            linhas.append(f"💬 “{texto}”")
        if a.get("target_url"):
            linhas.append(f"🔗 {a['target_url']}")
    autorizados, esperando = _fila()
    if autorizados or esperando:
        partes = []
        if autorizados:
            partes.append(f"🕗 {len(autorizados)} autorizado(s) esperando para executar ({_por_tipo(autorizados)})")
        if esperando:
            partes.append(f"🗂️ {len(esperando)} esperando a sua aprovação ({_por_tipo(esperando)})")
        linhas.append("\n" + "\n".join(partes) + "\nQuer ver algum deles? Responda “fila autorizada” ou “para aprovar”.")
    return "\n".join(linhas)


def fila() -> str:
    """O que você já autorizou e ainda não foi executado, com quando sai."""
    autorizados, _ = _fila()
    if not autorizados:
        return "Nada autorizado esperando: tudo o que você aprovou já foi executado."
    rotulo = {"approved": "gerando o CV", "review_docs": "CV para você ler", "queued": "na fila"}
    linhas = [f"🕗 *Autorizados, esperando para executar* ({len(autorizados)}: {_por_tipo(autorizados)})"]
    for a in autorizados[:25]:
        quando = "⚡ executa já" if a.get("run_now") else "no horário (8h–20h)"
        linhas.append(f"\n{ROTULO_FEITO.get(a.get('kind'), '•')} #{a['id']} · {rotulo.get(a.get('status'), a.get('status'))} · {quando}\n*{_titulo(a)}*")
        if a.get("target_url"):
            linhas.append(f"🔗 {a['target_url']}")
    return "\n".join(linhas)


def aprovar(ids: Any = None, texto: str = "", tipo: str = "", agora: bool = False) -> str:
    """Aprova os itens. Com 'tipo' (vagas/comentarios/conexoes/seguir) e sem ids, aprova todos os daquele tipo que estão esperando.
    'texto' só vale para UM comentário: é o texto final que vai ser publicado.
    'agora' = executa já, mesmo fora do horário (8h–20h); sem ele, vai no próximo horário."""
    lista = _ids(ids)
    kind = TIPOS.get((tipo or "").lower().strip())
    if not lista and kind:
        lista = [a["id"] for a in _api("GET", "/automation/inbox").get(kind) or []]
    if not lista:
        return "Diga quais itens (ex.: “aprovar 12 15”) ou o tipo (vagas, comentários, conexões, seguir)."
    if texto and len(lista) > 1:
        return "Texto editado só vale para um comentário por vez: diga qual (#id)."
    ok, falhas = [], []
    for i in lista:
        try:
            corpo = {"text": texto} if texto else {}
            if agora:
                corpo["run_now"] = True
            a = _api("POST", f"/automation/actions/{i}/approve", corpo)
            ok.append(f"#{i}" + (" (vai gerar o CV primeiro)" if a.get("status") == "approved" else ""))
        except Erro as exc:
            falhas.append(f"#{i}: {_motivo(exc)}")
    quando = "\n⚡ Vai executar agora (um de cada vez, com intervalo entre eles)." if agora else "\n🕗 Vai no próximo horário (8h–20h)."
    return _resumo("Aprovado", ok, falhas) + (quando if ok else "") + _aviso_modo()


def rejeitar(ids: Any) -> str:
    ok, falhas = [], []
    for i in _ids(ids):
        try:
            _api("POST", f"/automation/actions/{i}/reject")
            ok.append(f"#{i}")
        except Erro as exc:
            falhas.append(f"#{i}: {_motivo(exc)}")
    return _resumo("Rejeitado", ok, falhas) if ok or falhas else "Diga quais itens rejeitar (ex.: “rejeitar 13”)."


def _um(ids: Any) -> Optional[int]:
    lista = _ids(ids)
    return lista[0] if len(lista) == 1 else None


def cv_ok(ids: Any) -> str:
    i = _um(ids)
    if i is None:
        return "Diga qual CV (#id) pode ir."
    _api("POST", f"/automation/actions/{i}/approve-docs")
    return f"✅ CV da #{i} liberado: a candidatura entra na fila." + _aviso_modo()


def confirmar_envio(ids: Any) -> str:
    i = _um(ids)
    if i is None:
        return "Diga qual envio (#id) confirmar."
    r = _api("POST", f"/automation/actions/{i}/confirm-submit")
    if (r or {}).get("status") == "queued":   # the wait had run out: it is filled again and sent, without asking again
        return f"🟢 #{i} confirmada: volta para a fila, é preenchida de novo e enviada sem esperar outra confirmação." + _aviso_modo()
    return f"🟢 Envio da #{i} confirmado: o navegador do servidor faz o clique final e confere a página."


def responder(ids: Any, respostas: Any) -> str:
    """respostas = [{pergunta, resposta}] (ou um texto 'pergunta = resposta; ...'). Ficam salvas para os próximos formulários."""
    i = _um(ids)
    if i is None:
        return "Diga a qual item (#id) são as respostas."
    if isinstance(respostas, str):
        respostas = [{"pergunta": p.split("=", 1)[0], "resposta": p.split("=", 1)[1]} for p in respostas.split(";") if "=" in p]
    itens = [{"question": str(r.get("pergunta") or r.get("question") or "").strip(), "answer": str(r.get("resposta") or r.get("answer") or "").strip()}
             for r in (respostas or []) if isinstance(r, dict)]
    itens = [r for r in itens if r["question"] and r["answer"]]
    if not itens:
        return "Mande as respostas como pergunta = resposta."
    _api("POST", f"/automation/needs-user/{i}/answer", {"answers": itens})
    return f"✅ #{i}: {len(itens)} resposta(s) salva(s); a ação voltou para a fila." + _aviso_modo()


def tentar_de_novo(ids: Any) -> str:
    i = _um(ids)
    if i is None:
        return "Diga qual item (#id) tentar de novo."
    _api("POST", f"/automation/actions/{i}/retry")
    return f"🔁 #{i} voltou para a fila." + _aviso_modo()


def cancelar(ids: Any) -> str:
    ok, falhas = [], []
    for i in _ids(ids):
        try:
            _api("POST", f"/automation/actions/{i}/cancel")
            ok.append(f"#{i}")
        except Erro as exc:
            falhas.append(f"#{i}: {_motivo(exc)}")
    return _resumo("Cancelado", ok, falhas) if ok or falhas else "Diga quais itens cancelar."


def vagas_salvas() -> str:
    """Pede ao CareerOps para ler agora as vagas salvas no LinkedIn; o resultado chega depois, num aviso."""
    r = _api("POST", "/automation/saved-import/run")
    if r.get("mode") == "off":
        return f"📥 Leitura das vagas salvas na fila (#{r.get('id')}), mas a automação está desligada no app: só roda quando ligar."
    if r.get("already"):
        return f"📥 Já estava na fila (#{r.get('id')}): vai agora. Aviso quantas vagas novas entraram."
    return f"📥 Lendo suas vagas salvas no LinkedIn (#{r.get('id')}). Aviso quantas vagas novas entraram."


def parar(motivo: str = "") -> str:
    _api("POST", "/automation/halt", {"reason": (motivo or "Parado pelo Paulo no WhatsApp")[:400]})
    return "⏹ Automação parada. Nada roda até você dizer “religar automação”."


def religar() -> str:
    _api("POST", "/automation/resume")
    return "▶️ Automação religada. O que estava pela metade é conferido na página antes de qualquer repetição." + _aviso_modo()


def comentar_link(url: str, sugestao: str = "", texto_post: str = "", autor: str = "") -> str:
    """Post do LinkedIn que o Paulo mandou: rascunha o comentário (seguindo a sugestão dele, se houver) e devolve para o OK."""
    if not url:
        achados = re.findall(r"https?://\S*linkedin\.com/\S+|(?<!\S)(?:www\.)?linkedin\.com/\S+", texto_post or sugestao or "")
        url = achados[0] if achados else ""
    if not url:
        return "Mande o link do post do LinkedIn."
    r = _api("POST", "/automation/bot/comment-link", {"url": url.strip().rstrip(".,)"), "suggestion": sugestao or "",
                                                      "post_text": texto_post or "", "author": autor or ""}, timeout=180)
    if not r.get("ok"):
        return r.get("detail") or "Não consegui rascunhar o comentário."
    modo = {"off": "\n(A automação está desligada: aprovado, ele espera na fila até ser ligada.)",
            "dry_run": "\n(A automação está em ensaio: digita, mas não publica.)"}.get(r.get("mode"), "")
    return _com_ref(_rascunho(r["action_id"], r.get("author"), r["text"], f" (li: {r.get('read_from')})") + modo,
                    {"tipo": "rascunho", "ids": [r["action_id"]]})


def _rascunho(action_id: int, autor: Optional[str], texto: str, extra: str = "", titulo: str = "Rascunho") -> str:
    return (f"💬 {titulo} para o post de {autor or 'autor não identificado'}{extra}:\n\n{texto}\n\n"
            "Responda a esta mensagem:\n"
            "✅ “ok” (no horário) ou “ok agora” · ❌ “não”\n"
            "🎯 Outra versão (já pronta): “técnico”, “elogio”, “pergunta”, “contraponto”, “complemento” ou “experiência”\n"
            "✏️ Um ajuste para a IA (ex.: “mais curto”) · 📝 “texto final: …” com o seu texto")


ROTULO_ANGULO = {"tecnico": "técnico", "elogio": "elogio + problema que resolve", "pergunta": "pergunta técnica",
                 "contraponto": "contraponto", "complemento": "complemento", "experiencia": "sua experiência"}


def revisar(ids: Any, pedido: str, angulo: str = "") -> str:
    """A IA reescreve um comentário que ainda espera a sua aprovação (com o seu pedido e/ou outro tipo de comentário);
    ele volta para você aprovar."""
    i = _um(ids)
    angulo = ANGULOS.get(_curto(angulo or ""), angulo if angulo in ROTULO_ANGULO else "")
    if i is None or not ((pedido or "").strip() or angulo):
        return "Responda ao rascunho com o que mudar."
    corpo = {"instruction": (pedido or "").strip()[:1000]}
    if angulo:
        corpo["angle"] = angulo
    try:
        a = _api("POST", f"/automation/actions/{i}/revise", corpo, timeout=180)
    except Erro as exc:
        return f"⚠️ {_motivo(exc)}"
    p = a.get("payload") or {}
    como = f" (tipo: {ROTULO_ANGULO[angulo]})" if angulo else f" (pedido: “{pedido.strip()[:120]}”)"
    return _com_ref(_rascunho(i, p.get("author") or a.get("title"), p.get("text") or "", como, "Revisado"),
                    {"tipo": "rascunho", "ids": [i]})


def sugestoes() -> str:
    return _api("GET", "/automation/suggestions")["text"]


def documentos(ids: Any) -> str:
    """Manda o CV e a carta da candidatura em revisão como PDF no chat."""
    i = _um(ids)
    if i is None:
        return "Diga de qual item (#id) quer o CV."
    acao = next((a for a in _api("GET", "/automation/needs-user").get("items") or [] if a["id"] == i), None)
    if not acao or acao.get("kind") != "apply":
        return f"#{i} não é uma candidatura esperando revisão."
    enviados = _enviar_arquivos([{"name": "CV", "path": f"/api/jobs/{acao['target_id']}/document.pdf?kind=resume"},
                                 {"name": "Carta", "path": f"/api/jobs/{acao['target_id']}/document.pdf?kind=cover"}], i)
    return f"📄 Mandei {enviados} arquivo(s) da #{i}." if enviados else "Não consegui gerar os PDFs agora."


def _motivo(exc: Exception) -> str:
    s = str(exc)
    if " 404:" in s:
        return "não está mais esperando isso (já foi decidido ou mudou de estado)"
    return s.split(": ", 1)[-1][:160]


def _resumo(verbo: str, ok: List[str], falhas: List[str]) -> str:
    out = []
    if ok:
        out.append(f"✅ {verbo}: {', '.join(ok)}")
    if falhas:
        out.append("⚠️ Não deu: " + "; ".join(falhas))
    return "\n".join(out)


def _aviso_modo() -> str:
    try:
        st = _api("GET", "/automation/status")
    except Erro:
        return ""
    state = st.get("state") or {}
    if state.get("halted_at"):
        return f"\n(A automação está parada: {state.get('halted_reason')}.)"
    return {"off": "\n(A automação está desligada no app: fica na fila até ser ligada.)",
            "dry_run": "\n(Modo ensaio: vai até antes do último clique.)"}.get(state.get("mode"), "")


# --------------------------------------------------------------------------- cron: avisos
def _enviar_arquivos(arquivos: List[Dict[str, str]], action_id: int) -> int:
    n = 0
    base = _cfg()["CAREEROPS_API_URL"].rsplit("/api", 1)[0]
    for f in arquivos:
        try:
            pdf = _api("GET", base + f["path"], raw=True, timeout=120)
        except Erro:
            continue
        n += midia.enviar_documento(pdf, f"{f['name']}-{action_id}.pdf", f"{f['name']} da #{action_id}")
    return n


def _ref_aviso(d: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """What a reply to this notice is about (CareerOps says it in data.reply)."""
    if d.get("reply") == "list" and d.get("ids"):
        return {"tipo": "list", "ids": d["ids"]}
    if d.get("reply") and d.get("action_id"):
        return {"tipo": d["reply"], "ids": [d["action_id"]], "error_code": d.get("error_code")}
    return None


def _enviar_com_id(texto: str) -> Optional[str]:
    """Como lembretes._enviar, mas devolve o id da mensagem no WhatsApp ('' se a Evolution não disse; None se falhou)."""
    e = lembretes.evolution()
    if not all(e.values()):
        return None
    req = urllib.request.Request(f"{e['EVOLUTION_API_URL']}/message/sendText/{e['EVOLUTION_INSTANCE']}",
                                 data=json.dumps({"number": e["EVOLUTION_HOME_CHANNEL"], "text": texto, "delay": 0,
                                                  "linkPreview": False}).encode(),
                                 headers={"apikey": e["EVOLUTION_API_KEY"], "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            if r.status not in (200, 201):
                return None
            corpo = json.loads(r.read() or b"{}")
    except Exception:
        return None
    return str(((corpo or {}).get("key") or {}).get("id") or "") if isinstance(corpo, dict) else ""


def avisos_tick() -> str:
    """Entrega o que o CareerOps preparou e marca como entregue. O que falhou fica para o próximo minuto."""
    try:
        itens = _api("GET", "/automation/bot/notifications?limit=20").get("items") or []
    except Erro as exc:
        return f"carreira: {exc}"
    entregues = []
    for n in itens:
        msg_id = _enviar_com_id(n["text"])
        if msg_id is None:
            break   # WhatsApp fora: tenta tudo de novo depois, na mesma ordem
        guardar_ref(msg_id, _ref_aviso(n.get("data") or {}))
        arquivos = (n.get("data") or {}).get("files") or []
        if arquivos:
            _enviar_arquivos(arquivos, (n.get("data") or {}).get("action_id") or 0)
        entregues.append(n["id"])
    if entregues:
        _api("POST", "/automation/bot/notifications/ack", {"ids": entregues})
    return f"carreira: {len(entregues)}/{len(itens)} aviso(s) entregue(s)" if itens else ""


# --------------------------------------------------------------------------- cron: e-mail
def _estado() -> Dict[str, Any]:
    try:
        with open(ESTADO, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _salvar_estado(d: Dict[str, Any]) -> None:
    tmp = ESTADO + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ESTADO)


def _ids_gmail(q: str) -> List[str]:
    ids, token = [], None
    while len(ids) < EMAIL_MAX:
        params = {"q": q, "maxResults": 100}
        if token:
            params["pageToken"] = token
        r = google._api("GET", f"{gmail.BASE}/messages", params=params)
        ids += [m["id"] for m in r.get("messages", [])]
        token = r.get("nextPageToken")
        if not token:
            break
    return ids[:EMAIL_MAX]


def _mensagem(mid: str) -> Dict[str, Any]:
    m = google._api("GET", f"{gmail.BASE}/messages/{mid}", params={"format": "full"})
    corpo = re.sub(r"\n{3,}", "\n\n", gmail._texto(m.get("payload", {})).strip())
    data = None
    if m.get("internalDate"):
        data = datetime.datetime.fromtimestamp(int(m["internalDate"]) / 1000, datetime.timezone.utc).isoformat()
    return {"message_id": (gmail._hdr(m, "Message-ID") or f"gmail:{mid}")[:500], "gmail_id": mid, "thread_id": m.get("threadId"),
            "sender": gmail._hdr(m, "From")[:500], "subject": gmail._hdr(m, "Subject")[:1000], "received_at": data, "body": corpo[:20000]}


def email_tick(agora: Optional[datetime.datetime] = None) -> str:
    """De hora em hora (7h às 22h): respostas de candidaturas e avisos do LinkedIn, lidos pelo Gmail do Paulo e repassados
    ao CareerOps, que filtra, classifica e prepara os avisos. Confirmações e recusas são arquivadas (lidas); o resto fica como
    está. Nada é apagado nem respondido."""
    if not google.conectado():
        return "carreira-email: Google não conectado"
    agora = agora or datetime.datetime.now(datetime.timezone.utc)
    est = _estado()
    ultimo = est.get("email_ok_em")
    primeira = not ultimo   # a primeira leitura (45 dias) só sugere: nenhuma vaga muda de status e não chegam avisos um a um
    dias = EMAIL_PRIMEIRA_LEITURA_DIAS if primeira else \
        max(1, (agora - datetime.datetime.fromisoformat(ultimo)).days + 1)
    try:
        q = _api("GET", f"/automation/email/gmail-query?days={min(dias, 60)}")["query"]
        ids = _ids_gmail(q)
        lidos = gravados = 0
        arquivados = 0
        for i in range(0, len(ids), EMAIL_LOTE):
            lote = [_mensagem(mid) for mid in ids[i:i + EMAIL_LOTE]]
            r = _api("POST", "/automation/email/ingest", {"messages": lote, "source": "lolo", "baseline": primeira}, timeout=900)
            lidos += r.get("read", 0)
            gravados += r.get("recorded", 0)
            arquivados += _arquivar(lote, r.get("archive") or [])
    except (Erro, RuntimeError) as exc:
        return f"carreira-email: FALHA {exc}"
    est["email_ok_em"] = agora.isoformat()
    _salvar_estado(est)
    return f"carreira-email: {lidos} lido(s), {gravados} novo(s) sobre candidaturas, {arquivados} arquivado(s)"


def _arquivar(lote: List[Dict[str, Any]], message_ids: List[str]) -> int:
    """O que o CareerOps disse que não precisa do Paulo (confirmação, visualização, recusa): marca como lido e tira da caixa
    de entrada. Nada é apagado. Próximas etapas (entrevista, teste, pergunta, proposta) nunca vêm nesta lista."""
    por_id = {m["message_id"]: m["gmail_id"] for m in lote if m.get("gmail_id")}
    feitos = []
    for mid in message_ids:
        gid = por_id.get(mid)
        if not gid:
            continue
        try:
            google._api("POST", f"{gmail.BASE}/messages/{gid}/modify", {"removeLabelIds": ["INBOX", "UNREAD"]})
            feitos.append(mid)
        except RuntimeError:
            continue   # fica para a próxima rodada: o CareerOps devolve de novo até ser marcado
    if feitos:
        _api("POST", "/automation/email/archived", {"message_ids": feitos})
    return len(feitos)
