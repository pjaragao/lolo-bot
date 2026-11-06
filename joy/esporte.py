"""Esporte: calendário, placar, classificação e onde assistir no Brasil. Só fontes gratuitas, sem chave:

- futebolnatv.com.br: jogos de ontem/hoje/amanhã (todas as ligas, inclusive estaduais como o Catarinense) e os próximos
  jogos de cada time, com os canais de TV/streaming do Brasil e o placar/minuto ao vivo;
- ESPN (site.api.espn.com): calendário por liga para qualquer data, classificação, agenda de times e NFL;
- TheSportsDB (chave grátis "123", ou THESPORTSDB_KEY): Campeonato Catarinense e Série D (que a ESPN não tem) e reserva
  quando ESPN/futebolnatv não trazem nada. Limites e o que vale a pena: /opt/data/docs/FONTES_ESPORTE.md.

Alertas dos times favoritos (FAVORITOS) saem pelo cron `esporte_tick.py`: 1h antes com onde assistir e o placar final.
"""
import datetime
import fcntl
import html
import json
import os
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

HOME = os.environ.get("HERMES_HOME", "/opt/data")
ESTADO = os.path.join(HOME, "esporte_estado.json")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
FNT = "https://www.futebolnatv.com.br"
ESPN = "https://site.api.espn.com/apis"
TSDB = "https://www.thesportsdb.com/api/v1/json/" + (os.environ.get("THESPORTSDB_KEY") or "123")
DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
GAME_PASS = "NFL Game Pass (DAZN) ✅"

# time -> slug da página no futebolnatv (None = descobre sozinho pelo 1º jogo que aparecer) e id na ESPN
FAVORITOS = {
    "Avaí": {"fnt": "avai-p97u3yip0s", "espn": "9966", "tsdb": "134738", "emoji": "🦁"},
    "Figueirense": {"fnt": None, "espn": "3461", "tsdb": "134462", "emoji": "⚫⚪"},
    "Fluminense": {"fnt": "fluminense-10x6z1o3qw", "espn": "3445", "tsdb": "134296", "emoji": "🇭🇺"},
}
# apelido -> código da liga na ESPN
LIGAS_ESPN = {
    "brasileirao": "bra.1", "serie a": "bra.1", "brasileirao serie a": "bra.1", "serie b": "bra.2", "brasileirao serie b": "bra.2",
    "serie c": "bra.3", "brasileirao serie c": "bra.3", "copa do brasil": "bra.copa_do_brazil",
    "libertadores": "conmebol.libertadores", "sul-americana": "conmebol.sudamericana", "sulamericana": "conmebol.sudamericana",
    "sudamericana": "conmebol.sudamericana", "champions": "uefa.champions", "champions league": "uefa.champions",
    "europa league": "uefa.europa", "conference league": "uefa.europa.conf", "premier league": "eng.1", "ingles": "eng.1",
    "la liga": "esp.1", "espanhol": "esp.1", "serie a italiana": "ita.1", "italiano": "ita.1", "bundesliga": "ger.1",
    "alemao": "ger.1", "ligue 1": "fra.1", "frances": "fra.1", "portugues": "por.1", "liga portugal": "por.1",
    "mundial de clubes": "fifa.cwc", "copa do mundo": "fifa.world", "nfl": "nfl",
    "catarinense": "tsdb:5687", "campeonato catarinense": "tsdb:5687", "serie d": "tsdb:5079", "brasileirao serie d": "tsdb:5079",
}
# código ESPN -> id da mesma liga no TheSportsDB (reserva quando a ESPN vem vazia, ex.: Série C da ESPN parada em 2025)
ESPN_TSDB = {"bra.1": "4351", "bra.2": "4404", "bra.3": "4625", "bra.copa_do_brazil": "4725"}
# ligas exibidas por padrão nas listas do dia (o resto só aparece com filtro ou todos=true)
PRINCIPAIS = ("brasileirao serie a", "brasileirao serie b", "brasileirao serie c", "brasileirao serie d", "copa do brasil",
              "libertadores", "sul-americana", "sulamericana", "champions league", "europa league", "conference league",
              "campeonato ingles", "campeonato espanhol", "campeonato italiano", "campeonato alemao", "campeonato frances",
              "campeonato portugues", "catarinense", "copa sc", "recopa", "supercopa", "mundial", "copa do mundo",
              "eliminatorias", "amistosos selecoes", "carioca", "paulista")

_cache: Dict[str, Any] = {}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _get(url: str, ttl: int = 600, accept: str = "text/html,*/*") -> bytes:
    hit = _cache.get(url)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept, "Accept-Language": "pt-BR,pt;q=0.9"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = r.read(4_000_000)
    _cache[url] = (time.time(), data)
    return data


def _json(url: str, ttl: int = 120) -> Dict[str, Any]:
    return json.loads(_get(url, ttl, "application/json"))


# --------------------------------------------------------------------------- futebolnatv
def _tokens(frag: str) -> List[str]:
    frag = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", frag)
    return [t for t in (re.sub(r"\s+", " ", html.unescape(x)).strip() for x in re.split(r"<[^>]+>", frag)) if t]


def _data_h3(txt: str, ref: datetime.date) -> Optional[datetime.date]:
    rel = {"hoje": 0, "amanha": 1, "ontem": -1}.get(_norm(txt).split(" ")[0] if txt else "")
    if rel is not None:
        return ref + datetime.timedelta(days=rel)
    m = re.search(r"(\d{1,2})/(\d{1,2})", txt)
    if not m:
        return None
    d, mes = int(m.group(1)), int(m.group(2))
    ano = ref.year + (1 if mes < ref.month - 6 else -1 if mes > ref.month + 6 else 0)
    try:
        return datetime.date(ano, mes, d)
    except ValueError:
        return None


def _cards(raw: str, data_padrao: Optional[datetime.date] = None) -> List[Dict[str, Any]]:
    """Extrai os cartões de jogo (<a href="/aovivo/...">) de uma página do futebolnatv."""
    hoje = datetime.date.today()
    h3s = [(m.start(), _data_h3(" ".join(_tokens(m.group(1))), hoje)) for m in re.finditer(r"(?is)<h3[^>]*>(.*?)</h3>", raw)]
    out = []
    for m in re.finditer(r'<a href="(/aovivo/[^"]+)"', raw):
        ini = raw.find(">", m.end()) + 1
        fim = raw.find("</article>", ini)
        card = raw[ini:fim if fim > 0 else ini + 8000]
        ia, ib = card.rfind("<", 0, card.find("jogo-card-team-a")), card.rfind("<", 0, card.find("jogo-card-team-b"))
        tm = re.search(r"<time[^>]*>\s*(\d{1,2}:\d{2})", card)
        if "jogo-card-team-b" not in card or ia < 0 or not tm:
            continue
        canais_ini = [x.start() for x in re.finditer(r'class="[^"]*\bborder-t\b', card)]
        ic = card.find(">", canais_ini[-1]) + 1 if canais_ini and canais_ini[-1] > ib else len(card)
        cab = _tokens(card[:tm.start()])
        status = [t for t in _tokens(card[tm.end():ia]) if t]
        ta, tb = _tokens(card[ia:ib]), _tokens(card[ib:ic])
        canais: List[str] = []
        for t in _tokens(card[ic:]):
            if t.startswith("(") and canais:
                canais[-1] += " " + t
            elif t not in ("—", "-"):
                canais.append(t)
        alt_a = re.search(r'alt="([^"]*)"', card[ia:ib])
        alt_b = re.search(r'alt="([^"]*)"', card[ib:ic])
        dia = data_padrao
        for pos, d in h3s:
            if pos < m.start() and d:
                dia = d
        st = " ".join(status).replace("\n", " ")
        out.append({
            "url": FNT + m.group(1), "liga": cab[0] if cab else "", "fase": (cab[1].lstrip("- ").strip() if len(cab) > 1 else ""),
            "data": dia, "hora": tm.group(1),
            "casa": html.unescape(alt_a.group(1)) if alt_a else (ta[0] if ta else "?"),
            "fora": html.unescape(alt_b.group(1)) if alt_b else (tb[0] if tb else "?"),
            "gols_casa": next((t for t in ta if t.isdigit()), None), "gols_fora": next((t for t in tb if t.isdigit()), None),
            "status": "encerrado" if "FIM" in st.upper() else ("intervalo" if "INTERVALO" in st.upper() else
                                                                 (f"ao vivo {st}" if st else "agendado")),
            "canais": canais,
        })
    return out


def _dia_slug(dia: str) -> (str, datetime.date):
    hoje = datetime.date.today()
    d = _norm(dia or "hoje")
    if d in ("ontem",):
        return "jogos-ontem", hoje - datetime.timedelta(days=1)
    if d in ("amanha",):
        return "jogos-amanha", hoje + datetime.timedelta(days=1)
    if d in ("aovivo", "ao vivo", "agora"):
        return "jogos-aovivo", hoje
    try:
        dt = datetime.date.fromisoformat(str(dia)[:10])
        delta = (dt - hoje).days
        if delta in (-1, 0, 1):
            return {-1: "jogos-ontem", 0: "jogos-hoje", 1: "jogos-amanha"}[delta], dt
    except ValueError:
        pass
    return "jogos-hoje", hoje


def jogos_dia(dia: str = "hoje", ttl: int = 300) -> List[Dict[str, Any]]:
    slug, dt = _dia_slug(dia)
    return _cards(_get(f"{FNT}/{slug}", ttl).decode("utf-8", "replace"), dt)


def _bate(j: Dict[str, Any], filtro: str) -> bool:
    f = _norm(filtro)
    alvo = _norm(f"{j['liga']} {j['fase']} {j['casa']} {j['fora']}")
    return all(p in alvo for p in f.split())


def _principal(j: Dict[str, Any]) -> bool:
    liga = _norm(j["liga"])
    favs = [_norm(t) for t in FAVORITOS]
    return any(_norm(p) in liga for p in PRINCIPAIS) or any(t in _norm(f"{j['casa']} {j['fora']}") for t in favs)


def _linha(j: Dict[str, Any], com_data: bool = False, com_liga: bool = True) -> str:
    quando = (f"{DIAS[j['data'].weekday()]} {j['data']:%d/%m} " if com_data and j.get("data") else "") + j["hora"]
    if j["gols_casa"] is not None and j["status"] != "agendado":
        jogo = f"{j['casa']} *{j['gols_casa']} x {j['gols_fora']}* {j['fora']}"
        st = {"encerrado": " (fim)", "intervalo": " (intervalo)"}.get(j["status"], f" 🔴 {j['status'].replace('ao vivo ', '')}"
                                                                     if j["status"].startswith("ao vivo") else "")
    else:
        jogo, st = f"{j['casa']} x {j['fora']}", ""
    tv = f" · 📺 {', '.join(j['canais'])}" if j["canais"] else " · 📺 sem transmissão informada"
    liga = f" — _{j['liga']}{' · ' + j['fase'] if j['fase'] else ''}_" if com_liga else ""
    return f"• {quando} {jogo}{st}{liga}{tv if j['status'] != 'encerrado' else ''}"


def onde_assistir(dia: str = "hoje", filtro: str = "", todos: bool = False) -> str:
    """Jogos do dia (ontem/hoje/amanhã/aovivo) com canais no Brasil, agrupados por liga."""
    js = jogos_dia(dia)
    if filtro:
        js = [j for j in js if _bate(j, filtro)]
    elif not todos:
        js = [j for j in js if _principal(j)]
    slug, dt = _dia_slug(dia)
    titulo = {"jogos-ontem": "ontem", "jogos-amanha": "amanhã", "jogos-aovivo": "ao vivo agora"}.get(slug, "hoje")
    if not js:
        return (f"Nenhum jogo {'de ' + filtro + ' ' if filtro else 'das ligas principais '}{titulo} ({dt:%d/%m}) no futebolnatv."
                + ("" if filtro or todos else " Use todos=true para ver todas as ligas."))
    por_liga: Dict[str, List[str]] = {}
    for j in sorted(js, key=lambda x: x["hora"]):
        por_liga.setdefault(f"{j['liga']}", []).append(_linha(j, com_liga=False))
    blocos = [f"*⚽ Jogos {titulo} — {DIAS[dt.weekday()]} {dt:%d/%m}*" + (f" ({filtro})" if filtro else "")]
    for liga, linhas in por_liga.items():
        blocos.append(f"*{liga}*\n" + "\n".join(linhas))
    return "\n\n".join(blocos) + "\n\n_Fonte: futebolnatv.com.br (horário de Brasília)_"


# --------------------------------------------------------------------------- times
def _estado() -> Dict[str, Any]:
    try:
        with open(ESTADO, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _salvar_estado(st: Dict[str, Any]) -> None:
    tmp = ESTADO + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ESTADO)


def _favorito(nome: str) -> Optional[str]:
    n = _norm(nome)
    return next((t for t in FAVORITOS if _norm(t) == n or _norm(t) in n), None)


def _slug_time(nome: str) -> Optional[str]:
    """Slug do time no futebolnatv: fixo nos favoritos, senão descoberto pela página de um jogo dele (e guardado)."""
    fav = _favorito(nome)
    if fav and FAVORITOS[fav]["fnt"]:
        return FAVORITOS[fav]["fnt"]
    st = _estado()
    n = _norm(fav or nome)
    if st.get("slugs", {}).get(n):
        return st["slugs"][n]
    for dia in ("hoje", "amanha", "ontem"):
        try:
            js = jogos_dia(dia)
        except Exception:
            continue
        for j in js:
            lados = [(_norm(j["casa"]), "a"), (_norm(j["fora"]), "b")]
            if not any(n == x or n in x.split() or x.startswith(n) for x, _ in lados):
                continue
            pag = _get(j["url"], 3600).decode("utf-8", "replace")
            for s in re.findall(r'href="/time/([a-z0-9-]+)"', pag):
                if _norm(s.rsplit("-", 1)[0]).startswith(n.split()[0]):
                    st.setdefault("slugs", {})[n] = s
                    _salvar_estado(st)
                    return s
    return None


def proximos_time(nome: str, n: int = 5) -> List[Dict[str, Any]]:
    slug = _slug_time(nome)
    if not slug:
        return []
    return _cards(_get(f"{FNT}/time/{slug}/jogos", 1800).decode("utf-8", "replace"))[:n]


def resultados_time(nome: str, n: int = 5) -> List[Dict[str, Any]]:
    slug = _slug_time(nome)
    if not slug:
        return []
    return _cards(_get(f"{FNT}/time/{slug}/resultados", 1800).decode("utf-8", "replace"))[:n]


def _espn_time_id(nome: str) -> Optional[str]:
    fav = _favorito(nome)
    if fav:
        return FAVORITOS[fav]["espn"]
    d = _json(f"https://site.web.api.espn.com/apis/common/v3/search?query={urllib.parse.quote(nome)}&type=team&limit=5", 86400)
    for it in d.get("items", []):
        if "s:600~" in str(it.get("uid", "")) and "U20" not in it.get("displayName", "") and "Ginásio" not in it.get("displayName", ""):
            return str(it["id"])
    return None


def _espn_agenda_time(nome: str, n: int = 5) -> List[str]:
    tid = _espn_time_id(nome)
    if not tid:
        return []
    d = _json(f"{ESPN}/site/v2/sports/soccer/all/teams/{tid}/schedule?fixture=true", 1800)
    out = []
    for e in d.get("events", [])[:n]:
        dt = _dt_espn(e["date"])
        liga = (e.get("league") or {}).get("name") or ""
        out.append(f"• {DIAS[dt.weekday()]} {dt:%d/%m %H:%M} {_nome_espn(e)} — _{liga}_")
    return out


def time_info(nome: str) -> str:
    """Próximos jogos (com onde assistir) e últimos resultados de um time."""
    fav = _favorito(nome) or nome
    prox, res = [], []
    try:
        prox, res = proximos_time(fav), resultados_time(fav, 3)
    except Exception:
        pass
    partes = [f"*{FAVORITOS.get(fav, {}).get('emoji', '⚽')} {fav}*"]
    if prox:
        partes.append("*Próximos jogos*\n" + "\n".join(_linha(j, com_data=True) for j in prox))
    else:
        try:
            ag = _espn_agenda_time(fav)
        except Exception:
            ag = []
        if ag:
            partes.append("*Próximos jogos* (ESPN, sem canais)\n" + "\n".join(ag))
        elif FAVORITOS.get(fav, {}).get("tsdb") and _tsdb_proximos(FAVORITOS[fav]["tsdb"]):
            partes.append("*Próximos jogos em casa* (TheSportsDB, sem canais)\n" + "\n".join(_tsdb_proximos(FAVORITOS[fav]["tsdb"])))
        else:  # ex.: estaduais/Copa SC que ainda não entraram no futebolnatv nem na ESPN
            import pesquisa
            partes.append(pesquisa.web(f"Próximos jogos do {fav} (futebol, Brasil): data, horário de Brasília, adversário, "
                                       f"competição e onde assistir (TV/streaming no Brasil).", titulo=f"Próximos jogos ({fav}, via web)"))
    if res:
        partes.append("*Últimos resultados*\n" + "\n".join(_linha(j, com_data=True) for j in res))
    return "\n\n".join(partes)


# --------------------------------------------------------------------------- ESPN (ligas, classificação, NFL)
def _dt_espn(s: str) -> datetime.datetime:
    utc = datetime.datetime.strptime(s.replace("Z", ""), "%Y-%m-%dT%H:%M").replace(tzinfo=datetime.timezone.utc) \
        if len(s) <= 17 else datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return utc.astimezone().replace(tzinfo=None)


def _nome_espn(e: Dict[str, Any]) -> str:
    comp = e["competitions"][0]
    cs = sorted(comp["competitors"], key=lambda c: c.get("homeAway") != "home")
    nomes = [c["team"].get("shortDisplayName") or c["team"]["displayName"] for c in cs]
    st = comp["status"]["type"] if "status" in comp else e["status"]["type"]
    if st.get("state") in ("in", "post"):
        g = [c["score"].get("displayValue", "?") if isinstance(c.get("score"), dict) else c.get("score", "?") for c in cs]
        return f"{nomes[0]} *{g[0]} x {g[1]}* {nomes[1]}" + (" (fim)" if st.get("state") == "post" else f" 🔴 {st.get('shortDetail', '')}")
    return f"{nomes[0]} x {nomes[1]}"


def _liga_codigo(liga: str) -> Optional[str]:
    n = _norm(liga)
    if n in LIGAS_ESPN:
        return LIGAS_ESPN[n]
    if "." in str(liga):
        return str(liga)
    return next((v for k, v in sorted(LIGAS_ESPN.items(), key=lambda kv: -len(kv[0])) if k in n), None)


def calendario_liga(liga: str, data: Optional[str] = None, dias: int = 7) -> str:
    """Jogos de uma liga (ESPN) a partir de `data` por `dias` dias, com placar quando já começou."""
    cod = _liga_codigo(liga)
    if not cod:
        return f"Liga '{liga}' não reconhecida. Opções: " + ", ".join(sorted(set(LIGAS_ESPN)))
    if cod == "nfl":
        return nfl()
    if cod.startswith("tsdb:"):
        return calendario_tsdb(cod[5:], data, dias, liga)
    d0 = datetime.date.fromisoformat(str(data)[:10]) if data else datetime.date.today()
    dias = max(1, min(int(dias or 7), 14))
    eventos, nome = {}, liga
    for k in range(-1, dias + 1):  # a ESPN agrupa pelo dia dos EUA: um dia a mais de cada lado
        d = d0 + datetime.timedelta(days=k)
        try:
            j = _json(f"{ESPN}/site/v2/sports/soccer/{cod}/scoreboard?dates={d:%Y%m%d}", 300)
        except Exception:
            continue
        nome = (j.get("leagues") or [{}])[0].get("name") or nome
        for e in j.get("events", []):
            eventos[e["id"]] = e
    out = []
    for e in sorted(eventos.values(), key=lambda e: e["date"]):
        dt = _dt_espn(e["date"])
        if d0 <= dt.date() < d0 + datetime.timedelta(days=dias):
            out.append(f"• {DIAS[dt.weekday()]} {dt:%d/%m %H:%M} {_nome_espn(e)}")
    if not out and cod in ESPN_TSDB:
        return calendario_tsdb(ESPN_TSDB[cod], data, dias, nome)
    if not out:
        return f"Nenhum jogo de {nome} entre {d0:%d/%m} e {d0 + datetime.timedelta(days=dias - 1):%d/%m} (ESPN)."
    return (f"*🏆 {nome} — {d0:%d/%m} a {d0 + datetime.timedelta(days=dias - 1):%d/%m}*\n" + "\n".join(out)
            + "\n\n_Para canais no Brasil use esporte_onde_assistir (hoje/amanhã) ou esporte_time._")


# --------------------------------------------------------------------------- TheSportsDB (chave grátis: poucos itens por chamada)
def _tsdb(path: str, ttl: int = 1800) -> Dict[str, Any]:
    """GET no TheSportsDB; com a chave grátis o Cloudflare bloqueia rajadas (erro 1015/429): nesse caso devolve {}."""
    try:
        return json.loads(_get(f"{TSDB}/{path}", ttl, "application/json"))
    except Exception:
        return {}


def _tsdb_dt(e: Dict[str, Any]) -> datetime.datetime:
    ts = e.get("strTimestamp") or f"{e.get('dateEvent')}T{e.get('strTime') or '00:00:00'}"  # UTC
    utc = datetime.datetime.fromisoformat(ts[:19]).replace(tzinfo=datetime.timezone.utc)
    return utc.astimezone().replace(tzinfo=None)


def _tsdb_linha(e: Dict[str, Any]) -> str:
    dt = _tsdb_dt(e)
    if e.get("intHomeScore") not in (None, "") and e.get("strStatus") not in ("NS", "", None):
        jogo = f"{e['strHomeTeam']} *{e['intHomeScore']} x {e['intAwayScore']}* {e['strAwayTeam']}" + (" (fim)" if e.get("strStatus") == "FT" else "")
    else:
        jogo = f"{e['strHomeTeam']} x {e['strAwayTeam']}"
    return f"• {DIAS[dt.weekday()]} {dt:%d/%m %H:%M} {jogo}" + (f" — _{e['strVenue']}_" if e.get("strVenue") else "")


def calendario_tsdb(liga_id: str, data: Optional[str] = None, dias: int = 7, nome: str = "") -> str:
    d0 = datetime.date.fromisoformat(str(data)[:10]) if data else datetime.date.today()
    dias = max(1, min(int(dias or 7), 10))
    evs, cheio = {}, False
    for k in range(-1, dias + 1):  # dateEvent é UTC: um dia a mais de cada lado
        r = _tsdb(f"eventsday.php?d={d0 + datetime.timedelta(days=k):%Y-%m-%d}&l={liga_id}").get("events") or []
        cheio |= len(r) >= 3
        evs.update({e["idEvent"]: e for e in r})
    linhas = [_tsdb_linha(e) for e in sorted(evs.values(), key=_tsdb_dt)
              if d0 <= _tsdb_dt(e).date() < d0 + datetime.timedelta(days=dias)]
    nome = next((e["strLeague"] for e in evs.values()), nome or liga_id)
    if not linhas:
        return (f"Nenhum jogo de {nome} entre {d0:%d/%m} e {d0 + datetime.timedelta(days=dias - 1):%d/%m} (TheSportsDB)."
                + (" O Catarinense vai de janeiro a abril." if liga_id == "5687" else ""))
    return (f"*🏆 {nome} — {d0:%d/%m} a {d0 + datetime.timedelta(days=dias - 1):%d/%m}*\n" + "\n".join(linhas)
            + ("\n_TheSportsDB grátis mostra no máximo 3 jogos por dia: pode faltar jogo._" if cheio else "")
            + "\n_Canais: esporte_onde_assistir (hoje/amanhã)._")


def _tsdb_proximos(team_id: str) -> List[str]:
    """Próximos jogos do time (a chave grátis só devolve os jogos em casa)."""
    return [_tsdb_linha(e) + f" — _{e.get('strLeague', '')}_" for e in _tsdb(f"eventsnext.php?id={team_id}").get("events") or []]


def classificacao(liga: str, n: int = 20) -> str:
    cod = _liga_codigo(liga)
    if not cod:
        return f"Liga '{liga}' não reconhecida."
    if cod.startswith("tsdb:"):
        t = _tsdb(f"lookuptable.php?l={cod[5:]}").get("table") or []
        if not t:
            return "Classificação indisponível no TheSportsDB agora."
        t = sorted(t, key=lambda x: (-int(x.get("intPoints") or 0), -int(x.get("intGoalDifference") or 0)))
        return (f"*📊 {t[0].get('strLeague', liga)} {t[0].get('strSeason', '')}* — líderes (TheSportsDB grátis: só 5 times; "
                f"atualizado em {str(t[0].get('dateUpdated', ''))[:10]})\n"
                + "\n".join(f"• {x['strTeam']} — {x['intPoints']} pts ({x['intPlayed']}j, saldo {x['intGoalDifference']})"
                             + (f" · forma {x['strForm']}" if x.get("strForm") else "") for x in t))
    esporte = "football" if cod == "nfl" else "soccer"
    d = _json(f"{ESPN}/v2/sports/{esporte}/{cod}/standings", 1800)
    grupos = d.get("children") or [d]
    out = [f"*📊 Classificação — {d.get('name') or liga}*"]
    for g in grupos:
        ents = (g.get("standings") or {}).get("entries") or []
        if not ents:
            continue
        if len(grupos) > 1:
            out.append(f"\n*{g.get('name', '')}*")
        def stat(e, k):
            return next((s.get("displayValue") for s in e["stats"] if s.get("name") == k), "")
        ents = sorted(ents, key=lambda e: float(stat(e, "rank") or stat(e, "playoffSeed") or 99))
        for e in ents[:n]:
            if esporte == "soccer":
                out.append(f"{stat(e, 'rank')}. {e['team']['displayName']} — {stat(e, 'points')} pts "
                           f"({stat(e, 'gamesPlayed')}j {stat(e, 'wins')}v {stat(e, 'ties')}e {stat(e, 'losses')}d, saldo {stat(e, 'pointDifferential')})")
            else:
                out.append(f"• {e['team']['displayName']} — {stat(e, 'wins')}-{stat(e, 'losses')}"
                           + (f"-{stat(e, 'ties')}" if stat(e, "ties") not in ("", "0") else ""))
    return "\n".join(out) if len(out) > 1 else "Classificação indisponível para essa liga agora."


def nfl(semana: Optional[int] = None, time_nome: str = "") -> str:
    """Rodada da NFL (ESPN): horário de Brasília, placar ao vivo/final. Paulo assiste tudo pelo Game Pass."""
    url = f"{ESPN}/site/v2/sports/football/nfl/scoreboard" + (f"?week={int(semana)}&seasontype=2" if semana else "")
    d = _json(url, 120)
    wk = (d.get("week") or {}).get("number", "?")
    linhas = []
    for e in sorted(d.get("events", []), key=lambda e: e["date"]):
        if time_nome and _norm(time_nome) not in _norm(e["name"] + " " + e.get("shortName", "")):
            continue
        comp = e["competitions"][0]
        dt = _dt_espn(e["date"])
        cs = sorted(comp["competitors"], key=lambda c: c.get("homeAway") == "home")  # NFL: visitante @ mandante
        st = comp["status"]["type"]
        if st["state"] == "pre":
            jogo = f"{cs[0]['team']['abbreviation']} @ {cs[1]['team']['abbreviation']}"
            extra = ""
        else:
            jogo = f"{cs[0]['team']['abbreviation']} *{cs[0].get('score', '?')}* @ *{cs[1].get('score', '?')}* {cs[1]['team']['abbreviation']}"
            extra = " (fim)" if st["state"] == "post" else f" 🔴 {st.get('shortDetail', '')}"
        tv = ", ".join(n for b in comp.get("broadcasts", []) for n in b.get("names", []))
        linhas.append(f"• {DIAS[dt.weekday()]} {dt:%d/%m %H:%M} {jogo}{extra}" + (f" _(EUA: {tv})_" if tv and st["state"] == "pre" else ""))
    if semana is None and d.get("events") and all(e["competitions"][0]["status"]["type"]["state"] == "post" for e in d["events"]) \
            and isinstance(wk, int) and wk < 18:
        return nfl(wk + 1, time_nome)  # rodada encerrada: mostra a próxima
    bye = ", ".join(t["abbreviation"] for t in (d.get("week") or {}).get("teamsOnBye", []))
    if not linhas:
        return f"Nenhum jogo da NFL encontrado (semana {wk})."
    return (f"*🏈 NFL — semana {wk}*\n" + "\n".join(linhas) + (f"\n_Folga: {bye}_" if bye else "")
            + f"\n\n📺 Todos os jogos: {GAME_PASS}")


def placar(filtro: str = "") -> str:
    """Placar ao vivo/do dia: jogos em andamento + encerrados de hoje (futebolnatv) e NFL quando pedida."""
    if _norm(filtro) in ("nfl", "futebol americano"):
        return nfl()
    js = jogos_dia("hoje")
    js = [j for j in js if (_bate(j, filtro) if filtro else _principal(j)) and j["status"] != "agendado"]
    if not js:
        return "Nenhum jogo em andamento ou encerrado hoje" + (f" para '{filtro}'." if filtro else " nas ligas principais.")
    vivos = [j for j in js if j["status"] != "encerrado"]
    fim = [j for j in js if j["status"] == "encerrado"]
    out = []
    if vivos:
        out.append("*🔴 Ao vivo*\n" + "\n".join(_linha(j) for j in vivos))
    if fim:
        out.append("*✅ Encerrados hoje*\n" + "\n".join(_linha(j) for j in fim))
    return "\n\n".join(out)


# --------------------------------------------------------------------------- favoritos: resumo e alertas
def jogos_favoritos(dia: datetime.date) -> List[Dict[str, Any]]:
    out = []
    for t in FAVORITOS:
        try:
            for j in proximos_time(t, 3):
                if j.get("data") == dia:
                    out.append(dict(j, time=t))
        except Exception:
            continue
    return sorted(out, key=lambda j: j["hora"])


def resumo_favoritos(dia: Optional[datetime.date] = None) -> str:
    """Bloco para o bom-dia: jogos de Avaí/Figueirense/Fluminense no dia, com onde assistir."""
    js = jogos_favoritos(dia or datetime.date.today())
    return "\n".join(f"{FAVORITOS[j['time']]['emoji']} {_linha(j)[2:]}" for j in js)


def _enviar(texto: str) -> bool:
    import lembretes
    return lembretes._enviar(texto)


class _Lock:
    def __enter__(self):
        self.f = open(ESTADO + ".lock", "w")
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


JANELA_INTERVALO = (45, 80)     # minutos após o início em que o intervalo pode acontecer
JANELA_FIM = (100, 200)         # minutos após o início em que o jogo costuma acabar (prorrogação/atraso inclusos)


def _jogos_de_hoje_favoritos(hoje: datetime.date) -> List[Dict[str, Any]]:
    """1 requisição por dia: jogos de hoje dos favoritos (da página do dia do futebolnatv)."""
    out = []
    for j in jogos_dia("hoje"):
        for t in FAVORITOS:
            if _norm(t) in _norm(f"{j['casa']} {j['fora']}") and j.get("data") == hoje:
                h, m = map(int, j["hora"].split(":"))
                out.append({"url": j["url"], "time": t, "inicio": datetime.datetime.combine(hoje, datetime.time(h, m)).isoformat(),
                            "intervalo": False, "fim": False})
                break
    return out


def _msg_placar(j: Dict[str, Any], time_fav: str, fim: bool) -> str:
    gc, gf = int(j["gols_casa"] or 0), int(j["gols_fora"] or 0)
    emoji = FAVORITOS[time_fav]["emoji"]
    liga = f"_{j['liga']}{' · ' + j['fase'] if j['fase'] else ''}_"
    placar_txt = f"{j['casa']} *{gc} x {gf}* {j['fora']}"
    if not fim:
        return f"{emoji} ⏸️ *Intervalo* — {placar_txt}\n{liga}"
    casa = _norm(time_fav) in _norm(j["casa"])
    nosso, deles = (gc, gf) if casa else (gf, gc)
    res = "🎉 Vitória!" if nosso > deles else ("😐 Empate." if nosso == deles else "😞 Derrota.")
    return f"{emoji} 🏁 *Fim de jogo* — {placar_txt}\n{res} {liga}"


def tick(now: Optional[datetime.datetime] = None) -> str:
    """Cron (a cada minuto, só nas horas de jogo; fora das janelas de intervalo/fim não consulta nada): avisa o placar no INTERVALO e no FIM dos jogos dos
    favoritos. A programação do dia vai nas mensagens de bom dia/fim do dia (sem alertas de 'jogo hoje').
    Requisições: 1 por dia para montar a lista + 1 por minuto só nas janelas do intervalo e do fim (~15 por jogo)."""
    now = now or datetime.datetime.now()
    hoje = now.date()
    enviados = []
    with _Lock():
        st = _estado()
        dia = st.get("dia") or {}
        if dia.get("data") != hoje.isoformat():
            try:
                jogos = _jogos_de_hoje_favoritos(hoje)
            except Exception:
                return "sem lista do dia (fonte indisponível); tenta no próximo tick"
            dia = {"data": hoje.isoformat(), "jogos": jogos}
            st["dia"] = dia
            _salvar_estado(st)
        pend = [g for g in dia["jogos"] if not (g["intervalo"] and g["fim"])]
        ativos = []
        for g in pend:
            dec = (now - datetime.datetime.fromisoformat(g["inicio"])).total_seconds() / 60
            if (not g["intervalo"] and JANELA_INTERVALO[0] <= dec <= JANELA_INTERVALO[1]) or \
               (not g["fim"] and JANELA_FIM[0] <= dec <= JANELA_FIM[1]):
                ativos.append(g)
        if not ativos:
            return "fora das janelas: nenhuma requisição"
        try:
            vivos = {j["url"]: j for j in jogos_dia("hoje", ttl=55)}   # job roda a cada minuto na janela: dado de no máx. ~1 min
        except Exception:
            return "fonte indisponível; tenta no próximo tick"
        for g in ativos:
            j = vivos.get(g["url"])
            if not j or j["gols_casa"] is None:
                continue
            if j["status"] == "intervalo" and not g["intervalo"]:
                if _enviar(_msg_placar(j, g["time"], False)):
                    g["intervalo"] = True
                    enviados.append(g["url"] + "#intervalo")
            elif j["status"] == "encerrado" and not g["fim"]:
                if _enviar(_msg_placar(j, g["time"], True)):
                    g["fim"], g["intervalo"] = True, True
                    enviados.append(g["url"] + "#fim")
        _salvar_estado(st)
    return f"enviados: {enviados}" if enviados else "sem novidade"


# --------------------------------------------------------------------------- agenda do job de placar (sem rodar à toa)
def _hermes(args: List[str]) -> str:
    import subprocess
    r = subprocess.run(["/opt/hermes/.venv/bin/hermes", "cron", *args], capture_output=True, text=True, timeout=60)
    return r.stdout + r.stderr


def _cron_id(nome: str) -> Optional[str]:
    atual = None
    for linha in _hermes(["list", "--all"]).splitlines():
        m = re.match(r"\s*([0-9a-f]{12})\s*\[", linha)
        if m:
            atual = m.group(1)
        elif atual and re.match(r"\s*Name:\s*" + re.escape(nome) + r"\s*$", linha):
            return atual
    return None


def programar_dia(now: Optional[datetime.datetime] = None) -> str:
    """Cron diário (08:00, 1 requisição): monta a lista de jogos dos favoritos e ajusta o horário do job `esporte-placar`
    para rodar SÓ entre o começo da janela do intervalo do 1º jogo e o fim da janela do último. Sem jogo: job pausado."""
    now = now or datetime.datetime.now()
    hoje = now.date()
    jid = _cron_id("esporte-placar")
    if not jid:
        return "job esporte-placar não encontrado"
    try:
        jogos = _jogos_de_hoje_favoritos(hoje)
    except Exception as exc:
        _hermes(["edit", jid, "--schedule", "*/10 12-23 * * *"])     # fonte fora do ar: faixa larga; o tick monta a lista depois
        _hermes(["resume", jid])
        return f"fonte indisponível ({type(exc).__name__}); job em faixa larga 12-23h"
    with _Lock():
        st = _estado()
        st["dia"] = {"data": hoje.isoformat(), "jogos": jogos}
        _salvar_estado(st)
    if not jogos:
        _hermes(["pause", jid])
        return "sem jogo dos favoritos hoje: esporte-placar pausado (zero execuções)"
    ini = [datetime.datetime.fromisoformat(g["inicio"]) for g in jogos]
    h1 = (min(ini) + datetime.timedelta(minutes=JANELA_INTERVALO[0])).hour
    fim = max(ini) + datetime.timedelta(minutes=JANELA_FIM[1])
    h2 = 23 if fim.date() > hoje else fim.hour          # cron não atravessa a meia-noite: limita a 23h59
    _hermes(["edit", jid, "--schedule", f"* {h1}-{h2} * * *"])
    _hermes(["resume", jid])
    return f"{len(jogos)} jogo(s) hoje: esporte-placar roda só das {h1}h às {h2}h59 ({', '.join(g['time'] for g in jogos)})"


# --------------------------------------------------------------------------- bloco "hoje à noite na TV" (fim do dia)
_BR = ("brasileirao", "copa do brasil", "libertadores", "sul-americana", "sulamericana", "catarinense", "carioca", "paulista",
       "copa sc", "recopa", "supercopa", "serie a", "serie b", "serie c", "serie d")


def _nfl_hoje(hoje: datetime.date) -> List[str]:
    d = _json(f"{ESPN}/site/v2/sports/football/nfl/scoreboard", 600)
    out = []
    for e in sorted(d.get("events", []), key=lambda e: e["date"]):
        dt = _dt_espn(e["date"])
        if dt.date() != hoje:
            continue
        comp = e["competitions"][0]
        st = comp["status"]["type"]
        if st["state"] == "post":
            continue
        cs = sorted(comp["competitors"], key=lambda c: c.get("homeAway") == "home")
        nomes = f"{cs[0]['team']['displayName']} @ {cs[1]['team']['displayName']}"
        vivo = f" 🔴 {st.get('shortDetail', 'ao vivo')}" if st["state"] == "in" else ""
        out.append(f"🏈 {dt:%H:%M} {nomes}{vivo} · 📺 {GAME_PASS}")
    return out


def tv_hoje_a_noite(hoje: Optional[datetime.date] = None, a_partir: str = "17:00", limite: int = 8) -> str:
    """Programação de TV de hoje à noite: futebol no Brasil (Avaí, Figueirense, Fluminense e Libertadores primeiro) e NFL.
    Sempre devolve algo (mesmo 'nenhum jogo'), para o Paulo ver que foi considerado."""
    hoje = hoje or datetime.date.today()
    linhas: List[tuple] = []
    try:
        for j in jogos_dia("hoje"):
            if j.get("data") != hoje or j["status"] == "encerrado" or j["hora"] < a_partir:
                continue
            fav = next((t for t in FAVORITOS if _norm(t) in _norm(f"{j['casa']} {j['fora']}")), None)
            liga = _norm(j["liga"])
            lib = any(k in liga for k in ("libertadores", "sul americana", "sulamericana"))
            br = any(k in liga for k in _BR)
            if not (fav or lib or br):
                continue
            prio = 0 if fav else (1 if lib else 2)
            emoji = FAVORITOS[fav]["emoji"] + " " if fav else ("🏆 " if lib else "⚽ ")
            linhas.append((prio, j["hora"], f"{emoji}{_linha(j)[2:]}"))
    except Exception:
        linhas.append((9, "99", "⚽ futebol: programação indisponível agora"))
    linhas.sort(key=lambda x: (x[0], x[1]))
    out = [l[2] for l in linhas[:limite]]
    if len(linhas) > limite:
        out.append(f"… +{len(linhas) - limite} jogo(s) no Brasil (pergunte 'onde assistir')")
    try:
        out += _nfl_hoje(hoje)
    except Exception:
        out.append("🏈 NFL: programação indisponível agora")
    return "\n".join(f"• {o}" if not o.startswith("•") else o for o in out) or "• nenhum jogo de futebol no Brasil nem da NFL hoje à noite"
