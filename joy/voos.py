"""Voos: status ao vivo pelo Flightradar24 (endpoint público, sem chave) e monitoramento que avisa sozinho no WhatsApp.

O agente só cria/cancela o monitoramento; quem consulta e avisa é o `tick()`, chamado pelo cron a cada minuto
(lembretes_tick.py). Avisa: início do acompanhamento, atraso/mudança de previsão (>= 10 min), decolagem, ~20 min antes
do pouso e o pouso (ou cancelamento/desvio). Depois do pouso o monitoramento se encerra.
"""
import datetime
import fcntl
import json
import os
import re
import unicodedata
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import lembretes

HOME = os.environ.get("HERMES_HOME", "/opt/data")
PATH = os.path.join(HOME, "voos_monitor.json")
LOCK = PATH + ".lock"
TZ = ZoneInfo("America/Sao_Paulo")
FR24 = "https://api.flightradar24.com/common/v1/flight/list.json"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
INTERVALO_MIN = 3          # de quanto em quanto tempo consulta um voo monitorado
MUDANCA_MIN = 10           # mudança de horário que vale um aviso
AVISO_POUSO_MIN = 20       # aviso de "pousa em ~X min"
CIAS = {"latam": "LA", "tam": "LA", "gol": "G3", "azul": "AD", "voepass": "2Z", "passaredo": "2Z", "tap": "TP",
        "aerolineas": "AR", "copa": "CM", "avianca": "AV", "american": "AA", "united": "UA", "delta": "DL",
        "air france": "AF", "klm": "KL", "iberia": "IB", "emirates": "EK", "qatar": "QR", "sky": "H2",
        "jetsmart": "JA", "lufthansa": "LH", "turkish": "TK", "british": "BA", "ita": "AZ"}
DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


# --------------------------------------------------------------------------- consulta
def numero(txt: str) -> str:
    """'LATAM 3088', 'la 3088', 'voo 1260 da Gol', 'G3-1260' → 'LA3088' / 'G31260'."""
    t = unicodedata.normalize("NFKD", txt or "").encode("ascii", "ignore").decode().lower()
    m = re.search(r"\b([a-z][a-z0-9]|[0-9][a-z])\s*-?\s*(\d{1,4})\b", t)
    if m and m.group(1) not in ("da", "de", "do", "no", "na", "em"):
        return (m.group(1) + m.group(2)).upper()
    num = re.search(r"\b(\d{2,4})\b", t)
    for nome, cod in sorted(CIAS.items(), key=lambda x: -len(x[0])):
        if re.search(rf"\b{nome}\b", t) and num:
            return cod + num.group(1)
    return re.sub(r"\s+", "", (txt or "").upper())


def _consultar(num: str) -> List[Dict[str, Any]]:
    url = FR24 + "?" + urllib.parse.urlencode({"query": num, "fetchBy": "flight", "page": 1, "limit": 25})
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read())
    return ((d.get("result") or {}).get("response") or {}).get("data") or []


def _dt(ts: Any) -> Optional[datetime.datetime]:
    return datetime.datetime.fromtimestamp(int(ts), TZ) if ts else None


def _resumo(f: Dict[str, Any]) -> Dict[str, Any]:
    t = f.get("time") or {}
    sch, real, est, other = (t.get(k) or {} for k in ("scheduled", "real", "estimated", "other"))
    ap = f.get("airport") or {}
    o, d = ap.get("origin") or {}, ap.get("destination") or {}
    generico = (((f.get("status") or {}).get("generic") or {}).get("status") or {}).get("text") or ""
    r = {"numero": ((f.get("identification") or {}).get("number") or {}).get("default") or "",
         "origem": ((o.get("code") or {}).get("iata")) or "?", "destino": ((d.get("code") or {}).get("iata")) or "?",
         "origem_cidade": (((o.get("position") or {}).get("region") or {}).get("city")) or "",
         "destino_cidade": (((d.get("position") or {}).get("region") or {}).get("city")) or "",
         "dep_prog": _dt(sch.get("departure")), "arr_prog": _dt(sch.get("arrival")),
         "dep_real": _dt(real.get("departure")), "arr_real": _dt(real.get("arrival")),
         "dep_est": _dt(est.get("departure")), "arr_est": _dt(est.get("arrival") or other.get("eta")),
         "aeronave": " ".join(x for x in (((f.get("aircraft") or {}).get("model") or {}).get("code") or "",
                                          (f.get("aircraft") or {}).get("registration") or "") if x),
         "generico": generico.lower(), "fr24_txt": (f.get("status") or {}).get("text") or ""}
    if r["generico"] in ("canceled", "cancelled"):
        r["fase"] = "cancelado"
    elif r["generico"] == "diverted":
        r["fase"] = "desviado"
    elif r["arr_real"] or r["generico"] == "landed":
        r["fase"] = "pousou"
    elif r["dep_real"] or r["generico"] == "departed" or (f.get("status") or {}).get("live"):
        r["fase"] = "em voo"
    else:
        r["fase"] = "aguardando"
    r["partida"] = r["dep_real"] or r["dep_est"] or r["dep_prog"]
    r["chegada"] = r["arr_real"] or r["arr_est"] or r["arr_prog"]
    return r


def _escolher(voos: List[Dict[str, Any]], data: Optional[datetime.date], agora: datetime.datetime) -> Optional[Dict]:
    rs = [_resumo(f) for f in voos]
    rs = [r for r in rs if r["dep_prog"]]
    if data:
        rs = [r for r in rs if r["dep_prog"].date() == data]
    if not rs:
        return None
    vivos = [r for r in rs if r["fase"] == "em voo"]
    if vivos:
        return vivos[0]
    hoje = [r for r in rs if r["dep_prog"].date() == agora.date()]
    # sem data: o de hoje (mesmo que já tenha pousado); senão o mais próximo de agora
    return min(hoje or rs, key=lambda r: abs((r["dep_prog"] - agora).total_seconds()))


def _hm(x: Optional[datetime.datetime]) -> str:
    return f"{x:%H:%M}" if x else "?"


def _atraso(real: Optional[datetime.datetime], prog: Optional[datetime.datetime]) -> str:
    if not (real and prog):
        return ""
    m = round((real - prog).total_seconds() / 60)
    return f" (+{m} min)" if m >= 5 else (f" ({m} min)" if m <= -5 else " (no horário)")


def texto(r: Dict[str, Any], agora: Optional[datetime.datetime] = None) -> str:
    agora = agora or datetime.datetime.now(TZ)
    fase = r["fase"]
    if fase == "pousou":
        linha = f"🛬 *Pousou às {_hm(r['arr_real'])}*{_atraso(r['arr_real'], r['arr_prog'])}"
    elif fase == "em voo":
        falta = round((r["chegada"] - agora).total_seconds() / 60) if r["chegada"] else None
        linha = (f"✈️ *Em voo* — decolou {_hm(r['dep_real'])}; pouso previsto *{_hm(r['chegada'])}*"
                 + (f" (em ~{falta} min)" if falta is not None and falta > 0 else ""))
    elif fase == "cancelado":
        linha = "❌ *Voo CANCELADO*"
    elif fase == "desviado":
        linha = "⚠️ *Voo DESVIADO* para outro aeroporto"
    elif r["dep_est"] and r["dep_prog"] and (r["dep_est"] - r["dep_prog"]).total_seconds() >= 300:
        linha = f"⏱️ *Atrasado* — partida prevista {_hm(r['dep_est'])}{_atraso(r['dep_est'], r['dep_prog'])}"
    else:
        linha = f"🕐 *Ainda não decolou* — partida prevista {_hm(r['partida'])}"
    rota = f"{r['origem']} → {r['destino']}"
    if r["origem_cidade"] or r["destino_cidade"]:
        rota += f" ({r['origem_cidade'] or r['origem']} → {r['destino_cidade'] or r['destino']})"
    dp = r["dep_prog"]
    return (f"*{r['numero']}* {rota} — {DIAS[dp.weekday()]} {dp:%d/%m}\n{linha}\n"
            f"• Partida: programada {_hm(r['dep_prog'])}"
            + (f" · real {_hm(r['dep_real'])}{_atraso(r['dep_real'], r['dep_prog'])}" if r["dep_real"]
               else f" · prevista {_hm(r['dep_est'])}" if r["dep_est"] else "") + "\n"
            f"• Chegada: programada {_hm(r['arr_prog'])}"
            + (f" · real {_hm(r['arr_real'])}{_atraso(r['arr_real'], r['arr_prog'])}" if r["arr_real"]
               else f" · prevista {_hm(r['arr_est'])}" if r["arr_est"] else "")
            + (f"\n• Aeronave: {r['aeronave']}" if r["aeronave"] else "")
            + f"\n_(Flightradar24 às {agora:%H:%M}, horário de Brasília)_")


def status(num: str, data: Optional[str] = None) -> str:
    n = numero(num)
    if not re.fullmatch(r"[A-Z0-9]{2}\d{1,4}", n):
        return f"Não entendi o número do voo ('{num}'). Mande algo como LA3088, G3 1260 ou 'Azul 4050'."
    agora = datetime.datetime.now(TZ)
    dia = datetime.date.fromisoformat(data[:10]) if data else None
    try:
        voos = _consultar(n)
    except Exception as exc:
        return (f"Não consegui o status ao vivo do {n} agora ({type(exc).__name__}). Não tenho horário atualizado: "
                f"não repita o horário do print/e-mail como se fosse o real. Link: https://www.flightradar24.com/data/flights/{n.lower()}")
    r = _escolher(voos, dia, agora)
    if not r:
        return (f"O Flightradar24 não tem o {n}" + (f" em {dia:%d/%m}" if dia else "") + ". Confira o número do voo "
                "(ex.: o print diz LA 3088?) ou a data.")
    return texto(r, agora)


# --------------------------------------------------------------------------- monitoramento
class _Lock:
    def __enter__(self):
        os.makedirs(HOME, exist_ok=True)
        self.f = open(LOCK, "w")
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


def _load() -> List[Dict[str, Any]]:
    try:
        with open(PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _save(rows: List[Dict[str, Any]]) -> None:
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    os.replace(tmp, PATH)


def monitorar(num: str, data: Optional[str] = None, desde: Optional[str] = None) -> str:
    """Passa a acompanhar o voo do dia `data` (padrão hoje) a partir de `desde` (HH:MM; padrão 1h antes da partida)."""
    n = numero(num)
    if not re.fullmatch(r"[A-Z0-9]{2}\d{1,4}", n):
        return f"Não entendi o número do voo ('{num}'). Mande algo como LA3088 ou G3 1260."
    agora = datetime.datetime.now(TZ)
    dia = datetime.date.fromisoformat(data[:10]) if data else agora.date()
    if desde and not re.fullmatch(r"\d{1,2}:\d{2}", str(desde).strip()):
        return "Erro: 'hora' (a partir de quando acompanhar) deve ser HH:MM."
    atual, aviso = None, ""
    try:
        atual = _escolher(_consultar(n), dia, agora)
        if not atual:
            return f"O Flightradar24 não tem o {n} em {dia:%d/%m}. Confira o número/data antes de eu monitorar."
    except Exception as exc:
        aviso = f"\n(Não consegui consultar agora — {type(exc).__name__}; o acompanhamento tenta de novo sozinho.)"
    if not desde:                           # padrão: 1h antes da partida programada (ou já, se isso passou)
        ini = (atual["dep_prog"] - datetime.timedelta(hours=1)) if atual else agora
        desde = "00:00" if ini.date() < dia else f"{max(ini, agora):%H:%M}"
    h, m = map(int, str(desde).strip().split(":"))
    desde = f"{h:02d}:{m:02d}"
    with _Lock():
        rows = _load()
        r = next((x for x in rows if x["ativo"] and x["numero"] == n and x["data"] == dia.isoformat()), None)
        if r:
            r["desde"] = desde
        else:
            r = {"id": max([x["id"] for x in rows] + [0]) + 1, "numero": n, "data": dia.isoformat(), "desde": desde,
                 "ativo": True, "criado_em": agora.isoformat(timespec="seconds"), "ultimo_check": None, "fase": None,
                 "partida": None, "chegada": None, "avisos": [], "falhas": 0}
            rows.append(r)
        _save(rows)
    return (f"📡 Monitoramento #{r['id']} ativo: *{n}* de {dia:%d/%m}, a partir das {desde}. Aviso sozinho aqui: "
            "início do acompanhamento, atraso ou mudança de previsão, decolagem, ~20 min antes do pouso e o pouso."
            + (f"\n\nAgora:\n{texto(atual, agora)}" if atual else "") + aviso)


def listar() -> str:
    rows = [r for r in _load() if r.get("ativo")]
    return "\n".join(f"• #{r['id']} {r['numero']} em {r['data']} desde {r['desde']} (fase: {r.get('fase') or 'ainda não consultado'})"
                     for r in rows) or "Nenhum voo sendo monitorado."


def cancelar(alvo: str) -> str:
    alvo = str(alvo or "").strip()
    n = numero(alvo) if not alvo.isdigit() else ""
    with _Lock():
        rows = _load()
        achados = [r for r in rows if r.get("ativo") and (str(r["id"]) == alvo or (n and r["numero"] == n))]
        for r in achados:
            r["ativo"] = False
        if achados:
            _save(rows)
    return f"Monitoramento cancelado: {', '.join(r['numero'] for r in achados)}." if achados else "Nenhum monitoramento ativo com esse voo/id."


def _mudou(antes: Optional[str], depois: Optional[datetime.datetime]) -> bool:
    if not depois:
        return False
    if not antes:
        return True
    return abs((depois - datetime.datetime.fromisoformat(antes)).total_seconds()) >= MUDANCA_MIN * 60


def _passo(r: Dict[str, Any], agora: datetime.datetime) -> Optional[str]:
    """Consulta o voo monitorado e devolve a mensagem a mandar (ou None). Atualiza r (estado) no lugar."""
    try:
        atual = _escolher(_consultar(r["numero"]), datetime.date.fromisoformat(r["data"]), agora)
    except Exception:
        atual = None
    if not atual:
        r["falhas"] = r.get("falhas", 0) + 1
        if r["falhas"] == 3 and "sem_status" not in r["avisos"]:
            r["avisos"].append("sem_status")
            return (f"⚠️ Não estou conseguindo o status ao vivo do *{r['numero']}* (Flightradar24 fora do ar ou sem o voo). "
                    f"Sigo tentando. Link: https://www.flightradar24.com/data/flights/{r['numero'].lower()}")
        return None
    r["falhas"] = 0
    fase_antes = r.get("fase")
    cabeca = None
    if fase_antes is None:
        cabeca = f"📡 *Acompanhando o {r['numero']}*"
    elif atual["fase"] != fase_antes:
        cabeca = {"em voo": "🛫 *Decolou!*", "pousou": "🛬 *Pousou!*", "cancelado": "❌ *Cancelado!*",
                  "desviado": "⚠️ *Desviado!*"}.get(atual["fase"], "ℹ️ *Atualização do voo*")
    elif atual["fase"] in ("aguardando", "em voo") and (_mudou(r.get("partida"), atual["partida"]) if atual["fase"] == "aguardando"
                                                        else _mudou(r.get("chegada"), atual["chegada"])):
        cabeca = "⏱️ *Mudou a previsão*"
    elif (atual["fase"] == "em voo" and atual["chegada"] and "aproximando" not in r["avisos"]
          and 0 < (atual["chegada"] - agora).total_seconds() <= AVISO_POUSO_MIN * 60):
        r["avisos"].append("aproximando")
        cabeca = f"🛬 *Pousa em ~{round((atual['chegada'] - agora).total_seconds() / 60)} min*"
    r["fase"] = atual["fase"]
    r["partida"] = atual["partida"].isoformat() if atual["partida"] else None
    r["chegada"] = atual["chegada"].isoformat() if atual["chegada"] else None
    if atual["fase"] in ("pousou", "cancelado", "desviado"):
        r["ativo"] = False
    return f"{cabeca}\n{texto(atual, agora)}" if cabeca else None


def tick(now: Optional[datetime.datetime] = None) -> str:
    agora = now or datetime.datetime.now(TZ)
    feitos = []
    with _Lock():
        rows = _load()
        mudou = False
        for r in rows:
            if not r.get("ativo"):
                continue
            dia = datetime.date.fromisoformat(r["data"])
            if dia < agora.date() - datetime.timedelta(days=1):
                r["ativo"], mudou = False, True     # voo de dias atrás que nunca fechou
                continue
            h, m = map(int, r["desde"].split(":"))
            if agora < datetime.datetime.combine(dia, datetime.time(h, m), TZ):
                continue
            if r.get("ultimo_check") and (agora - datetime.datetime.fromisoformat(r["ultimo_check"])).total_seconds() < INTERVALO_MIN * 60 - 5:
                continue
            antes = json.dumps(r, sort_keys=True)
            estado = json.loads(antes)
            msg = _passo(r, agora)
            if msg and not lembretes._enviar(msg):
                r.clear()
                r.update(estado)                    # não registra o aviso que não saiu: tenta de novo no próximo minuto
                feitos.append(f"#{r['id']} FALHA ao enviar")
                continue
            r["ultimo_check"] = agora.isoformat(timespec="seconds")
            mudou = True
            if msg:
                feitos.append(f"#{r['id']} avisado ({r['fase']})")
        if mudou:
            _save(rows)
    return "voos: " + ("; ".join(feitos) if feitos else "nada")
