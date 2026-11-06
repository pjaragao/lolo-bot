"""Testes offline do status e do monitoramento de voos (sem chamar o Flightradar24 nem o WhatsApp). Rodar:
   HERMES_HOME=/tmp/lolotest JOY_DIR=/home/paulojr/lolo-bot/joy python3 -I tests/test_voos.py
"""
import datetime
import os
import shutil
import sys

assert os.environ.get("HERMES_HOME", "").startswith("/tmp"), "use HERMES_HOME=/tmp/... (nunca o real)"
shutil.rmtree(os.environ["HERMES_HOME"], ignore_errors=True)
os.makedirs(os.environ["HERMES_HOME"])
sys.path.insert(0, os.environ.get("JOY_DIR", "/opt/joy"))

import lembretes  # noqa: E402
import voos  # noqa: E402

TZ = voos.TZ
DIA = datetime.date(2026, 10, 29)


def ts(h, m):
    return int(datetime.datetime.combine(DIA, datetime.time(h, m), TZ).timestamp())


def voo(dep_real=None, arr_real=None, dep_est=None, arr_est=None, status="scheduled", live=False):
    return {"identification": {"number": {"default": "LA3088"}},
            "status": {"live": live, "text": "", "generic": {"status": {"text": status}}},
            "aircraft": {"model": {"code": "A320"}, "registration": "PR-TYA"},
            "airport": {"origin": {"code": {"iata": "CGH"}, "position": {"region": {"city": "Sao Paulo"}}},
                        "destination": {"code": {"iata": "FLN"}, "position": {"region": {"city": "Florianopolis"}}}},
            "time": {"scheduled": {"departure": ts(17, 45), "arrival": ts(18, 50)},
                     "real": {"departure": dep_real, "arrival": arr_real},
                     "estimated": {"departure": dep_est, "arrival": arr_est}, "other": {}}}


# 1. número do voo
assert voos.numero("LATAM 3088") == "LA3088"
assert voos.numero("voo 1260 da Gol") == "G31260"
assert voos.numero("G3-1260") == "G31260"
assert voos.numero("azul 4050") == "AD4050"

# 2. linha do tempo de hoje (o voo decolou 18:17 e pousou 19:05)
ETAPAS = [
    ((16, 0), [voo()]),
    ((17, 0), [voo()]),
    ((17, 3), [voo(dep_est=ts(18, 10), status="estimated")]),             # atraso de 25 min → avisa
    ((17, 6), [voo(dep_est=ts(18, 12), status="estimated")]),             # +2 min → não avisa
    ((18, 18), [voo(dep_real=ts(18, 17), arr_est=ts(19, 6), status="departed", live=True)]),   # decolou
    ((18, 21), [voo(dep_real=ts(18, 17), arr_est=ts(19, 6), status="departed", live=True)]),   # nada
    ((18, 48), [voo(dep_real=ts(18, 17), arr_est=ts(19, 5), status="departed", live=True)]),   # ~17 min → avisa
    ((19, 6), [voo(dep_real=ts(18, 17), arr_real=ts(19, 5), status="landed")]),                # pousou → encerra
    ((19, 30), [voo(dep_real=ts(18, 17), arr_real=ts(19, 5), status="landed")]),
]
enviadas = []
lembretes._enviar = lambda t: enviadas.append(t) or True
etapa = {"dados": ETAPAS[0][1]}
voos._consultar = lambda n: etapa["dados"]

r = voos.monitorar("LATAM 3088", DIA.isoformat(), "17:00")
assert "Monitoramento #1 ativo" in r and "17:00" in r, r
assert "Monitoramento #1" in voos.monitorar("LA 3088", DIA.isoformat(), "17:00")   # não duplica
assert voos.listar().count("LA3088") == 1

log = []
for (h, m), dados in ETAPAS:
    etapa["dados"] = dados
    antes = len(enviadas)
    voos.tick(datetime.datetime.combine(DIA, datetime.time(h, m), TZ))
    log.append((f"{h:02d}:{m:02d}", enviadas[antes:]))

por_hora = {h: msgs for h, msgs in log}
assert por_hora["16:00"] == [], "antes do horário pedido não consulta"
assert "Acompanhando" in por_hora["17:00"][0]
assert "Mudou a previsão" in por_hora["17:03"][0] and "18:10" in por_hora["17:03"][0]
assert por_hora["17:06"] == [], "mudança pequena não vira aviso"
assert "Decolou" in por_hora["18:18"][0] and "18:17" in por_hora["18:18"][0]
assert por_hora["18:21"] == []
assert "Pousa em ~17 min" in por_hora["18:48"][0], por_hora["18:48"]
assert "Pousou" in por_hora["19:06"][0] and "19:05" in por_hora["19:06"][0]
assert por_hora["19:30"] == [], "depois do pouso o monitoramento acabou"
assert "Nenhum voo" in voos.listar()

# 3. se o WhatsApp falhar, o aviso não se perde
enviadas.clear()
voos.monitorar("G3 1260", DIA.isoformat(), "17:00")
etapa["dados"] = [voo()]
lembretes._enviar = lambda t: False
voos.tick(datetime.datetime.combine(DIA, datetime.time(17, 0), TZ))
lembretes._enviar = lambda t: enviadas.append(t) or True
voos.tick(datetime.datetime.combine(DIA, datetime.time(17, 1), TZ))
assert enviadas and "Acompanhando" in enviadas[0], enviadas
assert "cancelado" in voos.cancelar("G3 1260").lower()

print("OK — voos")
