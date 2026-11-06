"""Previsão do tempo de Florianópolis (Open-Meteo, sem chave).

Regra do Paulo: toda previsão traz chuva em % E volume em mm, vento em km/h COM a direção e, se entrar vento sul, a hora
da virada.
"""
import datetime
import json
import time
import urllib.request
from typing import Any, Dict, List, Optional

LAT, LON = -27.5954, -48.5480
URL = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s&timezone=America%%2FSao_Paulo&forecast_days=6"
       "&hourly=temperature_2m,precipitation_probability,precipitation,weathercode,windspeed_10m,winddirection_10m,windgusts_10m"
       "&daily=weathercode,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,"
       "windspeed_10m_max,windgusts_10m_max,winddirection_10m_dominant,uv_index_max,sunrise,sunset") % (LAT, LON)

COD = {0: "céu limpo ☀️", 1: "poucas nuvens 🌤️", 2: "parcialmente nublado ⛅", 3: "nublado ☁️", 45: "neblina 🌫️", 48: "neblina 🌫️",
       51: "garoa leve 🌦️", 53: "garoa 🌦️", 55: "garoa forte 🌦️", 61: "chuva fraca 🌧️", 63: "chuva 🌧️", 65: "chuva forte 🌧️",
       66: "chuva gelada 🌧️", 67: "chuva gelada 🌧️", 71: "neve ❄️", 73: "neve ❄️", 75: "neve ❄️", 80: "pancadas de chuva 🌦️",
       81: "pancadas de chuva 🌧️", 82: "pancadas fortes ⛈️", 95: "trovoadas ⛈️", 96: "trovoadas com granizo ⛈️",
       99: "trovoadas com granizo ⛈️"}
ROSA = ["N", "NNE", "NE", "ENE", "L", "ESE", "SE", "SSE", "S", "SSO", "SO", "OSO", "O", "ONO", "NO", "NNO"]
SUL = {"SSE", "S", "SSO", "SO"}  # o "vento sul" de Floripa (frente fria)
_cache: Dict[str, Any] = {"t": 0, "d": None}


def _get() -> Dict[str, Any]:
    now = time.time()
    if _cache["d"] and now - _cache["t"] < 900:
        return _cache["d"]
    erro = None
    for tentativa in range(3):  # a Open-Meteo às vezes responde "service is overloaded"
        try:
            with urllib.request.urlopen(URL, timeout=20) as r:
                d = json.loads(r.read())
            if "daily" in d:
                _cache.update(t=now, d=d)
                return d
            erro = RuntimeError(d.get("reason") or "resposta sem previsão")
        except Exception as exc:
            erro = exc
        time.sleep(2 * (tentativa + 1))
    if _cache["d"]:
        return _cache["d"]
    raise erro


def _desc(code: int) -> str:
    return COD.get(int(code), "tempo variável")


def _dir(graus: Optional[float]) -> str:
    return "?" if graus is None else ROSA[int((graus % 360) / 22.5 + 0.5) % 16]


def _dia_idx(d: Dict[str, Any], dia: datetime.date) -> int:
    return d["daily"]["time"].index(dia.isoformat())


def _horas(d: Dict[str, Any], dia: datetime.date, h0: int = 0, h1: int = 24) -> List[int]:
    return [i for i, t in enumerate(d["hourly"]["time"]) if t.startswith(dia.isoformat()) and h0 <= int(t[11:13]) < h1]


def _periodo(d: Dict[str, Any], dia: datetime.date, h0: int, h1: int) -> Dict[str, Any]:
    h = d["hourly"]
    idx = _horas(d, dia, h0, h1)
    if not idx:
        return {}
    vel = [h["windspeed_10m"][i] or 0 for i in idx]
    forte = idx[vel.index(max(vel))]
    return {"min": min(h["temperature_2m"][i] for i in idx), "max": max(h["temperature_2m"][i] for i in idx),
            "chuva": max(h["precipitation_probability"][i] or 0 for i in idx),
            "mm": sum(h["precipitation"][i] or 0 for i in idx),
            "cod": max((h["weathercode"][i] for i in idx), key=lambda c: (c >= 51, c)),
            "vento": max(vel), "rajada": max(h["windgusts_10m"][i] or 0 for i in idx),
            "dir": _dir(h["winddirection_10m"][forte])}


def virada_sul(d: Dict[str, Any], dia: datetime.date) -> Optional[str]:
    """Hora em que o vento vira para sul (3h sem sul antes e 3h de sul depois, olhando também o fim do dia anterior), ou
    aviso de vento sul predominante no dia. None se não tem vento sul relevante."""
    h = d["hourly"]
    idx = _horas(d, dia)
    if not idx:
        return None
    todos = list(range(max(0, idx[0] - 3), min(len(h["time"]), idx[-1] + 4)))
    sul = {i: _dir(h["winddirection_10m"][i]) in SUL for i in todos}
    for i in idx:
        antes, depois = [j for j in range(i - 3, i) if j in sul], [j for j in range(i, i + 3) if j in sul]
        if len(antes) == 3 and len(depois) == 3 and not any(sul[j] for j in antes) and all(sul[j] for j in depois):
            return (f"🌬️ *Virada para vento sul às {h['time'][i][11:16]}* ({_dir(h['winddirection_10m'][i])}, "
                    f"{h['windspeed_10m'][i]:.0f} km/h, rajadas {h['windgusts_10m'][i]:.0f} km/h)")
    if sum(sul[i] for i in idx) >= len(idx) * 0.5:
        return "🌬️ *Vento sul* predominante no dia"
    return None


def _vento_dia(d: Dict[str, Any], i: int) -> str:
    dl = d["daily"]
    return (f"vento até {dl['windspeed_10m_max'][i]:.0f} km/h {_dir(dl['winddirection_10m_dominant'][i])} "
            f"(rajadas {dl['windgusts_10m_max'][i]:.0f} km/h)")


def _chuva_dia(d: Dict[str, Any], i: int) -> str:
    dl = d["daily"]
    return f"chuva {dl['precipitation_probability_max'][i] or 0}% ({dl['precipitation_sum'][i] or 0:.1f} mm)"


def detalhado(dia: datetime.date) -> str:
    d = _get()
    try:
        i = _dia_idx(d, dia)
    except ValueError:
        return "Previsão indisponível para essa data."
    dl = d["daily"]
    linhas = [f"• {_desc(dl['weathercode'][i]).capitalize()} · *{dl['temperature_2m_min'][i]:.0f}°–{dl['temperature_2m_max'][i]:.0f}°C* · "
              f"{_chuva_dia(d, i)} · {_vento_dia(d, i)} · UV {dl['uv_index_max'][i]:.0f} · "
              f"☀️ {dl['sunrise'][i][11:]}–{dl['sunset'][i][11:]}"]
    for nome, a, b in (("Madrugada", 0, 6), ("Manhã", 6, 12), ("Tarde", 12, 18), ("Noite", 18, 24)):
        p = _periodo(d, dia, a, b)
        if p:
            linhas.append(f"  - {nome}: {p['min']:.0f}–{p['max']:.0f}°C, {_desc(p['cod'])}, chuva {p['chuva']}% ({p['mm']:.1f} mm), "
                          f"vento {p['vento']:.0f} km/h {p['dir']} (rajadas {p['rajada']:.0f})")
    v = virada_sul(d, dia)
    if v:
        linhas.append(v)
    return "\n".join(linhas)


def resumo(dia: datetime.date) -> str:
    d = _get()
    try:
        i = _dia_idx(d, dia)
    except ValueError:
        return "sem previsão"
    dl = d["daily"]
    v = virada_sul(d, dia)
    return (f"{_desc(dl['weathercode'][i])} {dl['temperature_2m_min'][i]:.0f}–{dl['temperature_2m_max'][i]:.0f}°C, "
            f"{_chuva_dia(d, i)}, {_vento_dia(d, i)}" + (f" · {v}" if v else ""))


def texto(dias: int = 1) -> str:
    hoje = datetime.date.today()
    if dias <= 1:
        return "*🌤️ Florianópolis hoje*\n" + detalhado(hoje)
    sem = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
    return "\n".join(f"• {sem[(hoje + datetime.timedelta(days=k)).weekday()]} {(hoje + datetime.timedelta(days=k)):%d/%m}: "
                     f"{resumo(hoje + datetime.timedelta(days=k))}"
                     for k in range(dias))
