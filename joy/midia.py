"""Geração de imagens e memes com o AGY (generate_image) e envio da imagem ao chat pelo Evolution."""
import base64
import json
import os
import urllib.request
from typing import Optional

import arquivos
import lembretes

AGY = os.environ.get("AGY_SHIM_URL", "http://172.26.0.1:8787").rstrip("/")


def _enviar_imagem(data: bytes, mime: str, legenda: str) -> bool:
    ext = "png" if mime.endswith("png") else "webp" if mime.endswith("webp") else "jpg"
    return _enviar_midia(data, mime, legenda, f"imagem.{ext}", "image")


def enviar_documento(data: bytes, nome: str, legenda: str = "", mime: str = "application/pdf") -> bool:
    """Manda um arquivo (ex.: o PDF de um contrato) como documento no chat do Paulo."""
    return _enviar_midia(data, mime, legenda, nome, "document")


def _enviar_midia(data: bytes, mime: str, legenda: str, nome: str, mediatype: str) -> bool:
    e = lembretes.evolution()
    if not all(e.values()):
        return False
    body = {"number": e["EVOLUTION_HOME_CHANNEL"], "mediatype": mediatype, "mimetype": mime, "caption": legenda,
            "fileName": nome, "media": base64.b64encode(data).decode()}
    req = urllib.request.Request(f"{e['EVOLUTION_API_URL']}/message/sendMedia/{e['EVOLUTION_INSTANCE']}",
                                 data=json.dumps(body).encode(),
                                 headers={"apikey": e["EVOLUTION_API_KEY"], "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status in (200, 201)
    except Exception:
        return False


def gerar(prompt: str, usar_base: bool = True, legenda: str = "", minutos: int = 60) -> str:
    """Gera a imagem (a partir da última imagem enviada, se houver e usar_base) e manda no chat."""
    if len((prompt or "").strip()) < 5:
        return "Erro: descreva a imagem/meme (e o texto exato de cada trecho)."
    body = {"kind": "image", "prompt": prompt}
    base_usada = ""
    if usar_base:
        rec = arquivos.recentes("image", minutos)
        if rec:
            with open(rec[0]["path"], "rb") as f:
                body["data_b64"] = base64.b64encode(f.read()).decode()
            body["mime"] = rec[0].get("mime") or "image/jpeg"
            base_usada = " (usei a imagem que você mandou como base)"
    req = urllib.request.Request(AGY + "/v1/task", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {os.environ.get('AGY_SHIM_TOKEN', '')}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=330) as r:
            out = json.loads(r.read())
    except Exception as exc:
        return f"Não consegui gerar a imagem agora ({type(exc).__name__}). Tente de novo em instantes."
    data = base64.b64decode(out["data_b64"])
    if not _enviar_imagem(data, out.get("mime", "image/jpeg"), legenda):
        return "Gerei a imagem, mas não consegui enviar ao chat."
    return f"🖼️ Imagem gerada e enviada no chat{base_usada}."


def sem_base() -> str:
    rec = arquivos.recentes("image", 60)
    return f"{len(rec)} imagem(ns) recente(s) disponível(is) como base."
