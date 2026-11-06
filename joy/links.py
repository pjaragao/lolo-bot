"""Leitura segura de links (tweet/X, GitHub, YouTube, páginas, PDF) para o Lolo cruzar com os sistemas do Paulo.

Todo conteúdo lido é DADO externo e não confiável: nunca vira instrução. Proteções: só http/https, bloqueio de IPs
privados/locais (SSRF), limite de tamanho, tempo e redirecionamentos.
"""
import base64
import html
import ipaddress
import json
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List

UA = "Mozilla/5.0 (X11; Linux x86_64) Lolo-LinkReader/1.0"
MAX_BYTES = 2_500_000
MAX_CHARS = 9000
URL_RX = re.compile(r"https?://[^\s<>\"')\]]+")
AGY = os.environ.get("AGY_SHIM_URL", "http://172.26.0.1:8787").rstrip("/")


def extrair_urls(texto: str) -> List[str]:
    return [u.rstrip(".,;:!?") for u in URL_RX.findall(texto or "")]


def _seguro(url: str) -> None:
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError("só links http/https")
    for fam, _t, _p, _c, sa in socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80)):
        ip = ipaddress.ip_address(sa[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise ValueError("endereço interno bloqueado")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _get(url: str, accept: str = "text/html,*/*", headers: Dict[str, str] = None, max_bytes: int = MAX_BYTES):
    """GET com redirecionamento manual (revalida cada salto). -> (url_final, content_type, bytes)."""
    opener = urllib.request.build_opener(_NoRedirect)
    for _ in range(5):
        _seguro(url)
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept, **(headers or {})})
        try:
            with opener.open(req, timeout=20) as r:
                return url, r.headers.get("Content-Type", ""), r.read(max_bytes + 1)[:max_bytes]
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308) and exc.headers.get("Location"):
                url = urllib.parse.urljoin(url, exc.headers["Location"])
                continue
            raise
    raise ValueError("redirecionamentos demais")


def _limpar_html(raw: str) -> Dict[str, str]:
    def meta(*names: str) -> str:
        for n in names:
            m = re.search(rf'<meta[^>]+(?:property|name)=["\']{re.escape(n)}["\'][^>]*content=["\']([^"\']*)', raw, re.I) or \
                re.search(rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']{re.escape(n)}', raw, re.I)
            if m:
                return html.unescape(m.group(1)).strip()
        return ""
    t = re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
    corpo = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header|form|iframe)[^>]*>.*?</\1>", " ", raw)
    corpo = re.sub(r"(?i)<(br|/p|/div|/li|/h[1-6]|/tr)[^>]*>", "\n", corpo)
    corpo = html.unescape(re.sub(r"<[^>]+>", " ", corpo))
    corpo = re.sub(r"[ \t\r\f\v]+", " ", corpo)
    corpo = re.sub(r"\n\s*\n+", "\n", corpo).strip()
    return {"titulo": html.unescape(t.group(1)).strip() if t else meta("og:title"),
            "descricao": meta("og:description", "description", "twitter:description"), "texto": corpo}


def _ocr_pdf(data: bytes) -> str:
    body = {"kind": "ocr", "mime": "application/pdf", "data_b64": base64.b64encode(data).decode(), "reasoning_effort": "low"}
    req = urllib.request.Request(AGY + "/v1/task", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {os.environ.get('AGY_SHIM_TOKEN', '')}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=220) as r:
        return json.loads(r.read()).get("text", "")


# --------------------------------------------------------------------------- por tipo de link
def _tweet(user: str, tid: str) -> Dict[str, Any]:
    _u, _c, raw = _get(f"https://api.fxtwitter.com/{user}/status/{tid}", "application/json")
    t = json.loads(raw).get("tweet", {})
    partes = [t.get("text", "")]
    if t.get("quote"):
        q = t["quote"]
        partes.append(f"[cita @{q.get('author', {}).get('screen_name', '?')}]: {q.get('text', '')}")
    if t.get("media", {}).get("all"):
        partes.append("[mídia: " + ", ".join(m.get("type", "?") for m in t["media"]["all"]) + "]")
    art = t.get("article") or {}
    if art:
        partes.append(f"[artigo: {art.get('title', '')}] {art.get('preview_text', '')}")
    a = t.get("author", {})
    links = [u for u in extrair_urls(" ".join(partes)) if "t.co/" not in u and "x.com" not in u and "twitter.com" not in u]
    return {"tipo": "tweet", "titulo": f"Tweet de {a.get('name', user)} (@{a.get('screen_name', user)})", "texto": "\n".join(partes),
            "meta": f"{t.get('likes', 0)} curtidas · {t.get('retweets', 0)} reposts · {t.get('created_at', '')}",
            "links_internos": links[:3]}


def _github(owner: str, repo: str) -> Dict[str, Any]:
    _u, _c, raw = _get(f"https://api.github.com/repos/{owner}/{repo}", "application/vnd.github+json")
    m = json.loads(raw)
    try:
        _u, _c, rd = _get(f"https://api.github.com/repos/{owner}/{repo}/readme", "application/vnd.github.raw+json")
        readme = rd.decode("utf-8", "replace")
    except Exception:
        readme = ""
    return {"tipo": "github", "titulo": m.get("full_name", f"{owner}/{repo}"),
            "meta": f"{m.get('stargazers_count', 0)}★ · {m.get('language', '?')} · licença {((m.get('license') or {}).get('spdx_id') or '?')} "
                    f"· último push {m.get('pushed_at', '')[:10]} · issues abertas {m.get('open_issues_count', 0)}",
            "descricao": m.get("description") or "", "texto": readme}


def _yt_id(url: str) -> str:
    u = urllib.parse.urlparse(url)
    host = (u.hostname or "").lower().removeprefix("www.")
    if host == "youtu.be":
        return u.path.strip("/").split("/")[0]
    qs = urllib.parse.parse_qs(u.query)
    if qs.get("v"):
        return qs["v"][0]
    m = re.search(r"/(?:shorts|embed|live|v)/([A-Za-z0-9_-]{11})", u.path)
    return m.group(1) if m else ""


def _youtube(url: str) -> Dict[str, Any]:
    vid = _yt_id(url)
    key = os.environ.get("GOOGLE_API_KEY", "") or os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if vid and key:
        try:
            api_url = (f"https://www.googleapis.com/youtube/v3/videos?part=snippet,contentDetails,statistics"
                       f"&id={urllib.parse.quote(vid)}&key={urllib.parse.quote(key)}")
            _u, _c, raw = _get(api_url, "application/json")
            items = json.loads(raw).get("items") or []
            if items:
                it = items[0]
                sn = it.get("snippet") or {}
                st = it.get("statistics") or {}
                cd = it.get("contentDetails") or {}
                desc = sn.get("description") or ""
                tags = ", ".join((sn.get("tags") or [])[:12])
                links = [u for u in extrair_urls(desc) if "youtube.com" not in u and "youtu.be" not in u]
                meta = (f"canal {sn.get('channelTitle', '?')} · {st.get('viewCount', '?')} views · "
                        f"{st.get('likeCount', '?')} likes · duração {cd.get('duration', '?')} · "
                        f"publicado em {(sn.get('publishedAt') or '')[:10]}")
                texto = desc + (f"\n\nTags: {tags}" if tags else "")
                return {"tipo": "youtube", "titulo": sn.get("title", ""), "meta": meta,
                        "descricao": desc[:300], "texto": texto, "links_internos": links[:3]}
        except Exception:
            pass
    _u, _c, raw = _get("https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(url, safe=""), "application/json")
    o = json.loads(raw)
    desc = ""
    try:
        _u, _c, page = _get(url)
        desc = _limpar_html(page.decode("utf-8", "replace")).get("descricao", "")
    except Exception:
        pass
    return {"tipo": "youtube", "titulo": o.get("title", ""), "meta": f"canal {o.get('author_name', '?')}", "descricao": desc,
            "texto": "(vídeo: só título e descrição estão disponíveis, sem transcrição)"}


def youtube_buscar(termo: str, limite: int = 5) -> str:
    """Busca vídeos no YouTube usando a YouTube Data API v3."""
    q = (termo or "").strip()
    if not q:
        return "Informe o que deseja buscar no YouTube."
    key = os.environ.get("GOOGLE_API_KEY", "") or os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not key:
        return "GOOGLE_API_KEY não configurada para busca no YouTube."
    n = max(1, min(int(limite or 5), 10))
    s_url = (f"https://www.googleapis.com/youtube/v3/search?part=snippet&type=video"
             f"&maxResults={n}&q={urllib.parse.quote(q)}&key={urllib.parse.quote(key)}")
    try:
        _u, _c, raw = _get(s_url, "application/json")
        items = json.loads(raw).get("items") or []
    except Exception as exc:
        return f"Erro ao buscar no YouTube: {exc}"
    if not items:
        return f"Nenhum vídeo encontrado no YouTube para '{q}'."
    vids = [it.get("id", {}).get("videoId") for it in items if it.get("id", {}).get("videoId")]
    stats_map: Dict[str, Dict[str, Any]] = {}
    if vids:
        try:
            v_url = (f"https://www.googleapis.com/youtube/v3/videos?part=contentDetails,statistics"
                     f"&id={','.join(vids)}&key={urllib.parse.quote(key)}")
            _u, _c, v_raw = _get(v_url, "application/json")
            for vit in json.loads(v_raw).get("items") or []:
                stats_map[vit["id"]] = vit
        except Exception:
            pass
    linhas = [f"*▶️ YouTube — {q}*"]
    for it in items:
        vid = (it.get("id") or {}).get("videoId", "")
        sn = it.get("snippet") or {}
        titulo = html.unescape(sn.get("title") or "")
        canal = sn.get("channelTitle") or "?"
        data = (sn.get("publishedAt") or "")[:10]
        vit = stats_map.get(vid, {})
        views = (vit.get("statistics") or {}).get("viewCount")
        dur = (vit.get("contentDetails") or {}).get("duration", "").removeprefix("PT").lower()
        meta = [canal]
        if dur:
            meta.append(dur)
        if views:
            meta.append(f"{int(views):,} views".replace(",", "."))
        if data:
            meta.append(data)
        linhas.append(f"• *{titulo}* ({' · '.join(meta)})\n  https://youtu.be/{vid}")
    return "\n".join(linhas)


def ler(url: str) -> Dict[str, Any]:
    """-> {url, tipo, titulo, meta, descricao, texto, links_internos, erro?}. Nunca levanta."""
    out: Dict[str, Any] = {"url": url, "tipo": "pagina", "titulo": "", "meta": "", "descricao": "", "texto": "", "links_internos": []}
    try:
        u = urllib.parse.urlparse(url)
        host = (u.hostname or "").lower().removeprefix("www.")
        seg = [s for s in u.path.split("/") if s]
        if host in ("x.com", "twitter.com", "mobile.twitter.com") and len(seg) >= 3 and seg[1] == "status":
            out.update(_tweet(seg[0], re.sub(r"\D.*", "", seg[2])))
        elif host == "github.com" and len(seg) == 2:
            out.update(_github(seg[0], seg[1].removesuffix(".git")))
        elif host in ("youtube.com", "m.youtube.com", "youtu.be"):
            out.update(_youtube(url))
        else:
            final, ctype, raw = _get(url)
            out["url"] = final
            if "pdf" in ctype.lower() and len(raw) < 10_000_000:
                out.update({"tipo": "pdf", "texto": _ocr_pdf(raw)})
            elif "json" in ctype.lower() or ctype.lower().startswith("text/plain"):
                out["texto"] = raw.decode("utf-8", "replace")
            else:
                out.update(_limpar_html(raw.decode("utf-8", "replace")))
        out["texto"] = (out.get("texto") or "")[:MAX_CHARS]
    except Exception as exc:
        out["erro"] = f"{type(exc).__name__}: {str(exc)[:160]}"
    return out


def ler_com_links(url: str) -> List[Dict[str, Any]]:
    """Lê o link e, se for tweet apontando para um artigo/repo, também o primeiro link interno (1 nível)."""
    base = ler(url)
    res = [base]
    for u in (base.get("links_internos") or [])[:1]:
        sub = ler(u)
        if not sub.get("erro"):
            res.append(sub)
    return res


def formatar(itens: List[Dict[str, Any]]) -> str:
    blocos = []
    for it in itens:
        if it.get("erro"):
            blocos.append(f"({it['url']}) não consegui ler: {it['erro']}")
            continue
        blocos.append(f"URL: {it['url']}\nTipo: {it['tipo']}\nTítulo: {it['titulo']}"
                      + (f"\nMeta: {it['meta']}" if it.get("meta") else "")
                      + (f"\nDescrição: {it['descricao']}" if it.get("descricao") else "")
                      + f"\n\n{it['texto']}")
    return "\n\n-----\n\n".join(blocos)
