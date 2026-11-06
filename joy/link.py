"""Ligação com o agente da SIÉ (sie-joy-bot). Tudo da SIÉ é acessível; toda ação que altera a SIÉ é executada pelo
endpoint do agente da SIÉ, que AVISA O GRUPO DA SIÉ automaticamente (não depende do modelo lembrar)."""
import json
import os
import urllib.request

URL = os.environ.get("SIE_LINK_URL", "http://sie-joy-bot:8660/agent/acao")
TOKEN = os.environ.get("SIE_LINK_TOKEN", "")
ORIGEM = f"{os.environ.get('PERSONA_NAME', 'Assistente')} (assistente do Paulo)"


def sie(consulta: str, args: dict) -> str:
    if not TOKEN:
        return "Ligação com a SIÉ não configurada."
    body = {"origem": ORIGEM, "consulta": consulta, "args": args or {}}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            out = json.loads(r.read())
    except Exception as exc:
        return f"Não consegui falar com o agente da SIÉ: {type(exc).__name__}"
    extra = "" if out.get("avisou_grupo") is not False else ""
    return str(out.get("resultado", "")) + extra
