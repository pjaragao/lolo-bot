"""Textos de agenda/tarefas e as mensagens programadas (bom dia e fim do dia) do Paulo."""
import concurrent.futures
import datetime
from typing import Any, Dict, List, Optional

import clima
import gmail
import google
import lembretes
from pessoas import LUISA_EMAIL

DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
TZ = google.TZ


def _dia_inicio(d: datetime.date) -> datetime.datetime:
    return datetime.datetime.combine(d, datetime.time(0, 0), tzinfo=TZ)


def eventos_do_dia(d: datetime.date) -> List[Dict[str, Any]]:
    return google.listar_eventos(_dia_inicio(d), _dia_inicio(d + datetime.timedelta(days=1)))


def eventos_por_dia(d0: datetime.date, dias: int, agenda: Optional[str] = None) -> Dict[datetime.date, List[Dict[str, Any]]]:
    """Busca todos os eventos do intervalo [d0, d0 + dias) em uma única consulta paralela e agrupa por dia."""
    dias = max(1, int(dias))
    todos = google.listar_eventos(_dia_inicio(d0), _dia_inicio(d0 + datetime.timedelta(days=dias)), agenda=agenda)
    por_dia: Dict[datetime.date, List[Dict[str, Any]]] = {}
    for k in range(dias):
        d = d0 + datetime.timedelta(days=k)
        ini_d, fim_d = _dia_inicio(d), _dia_inicio(d + datetime.timedelta(days=1))
        por_dia[d] = [e for e in todos if e["inicio"] < fim_d and (e["fim"] > ini_d or e["inicio"] == ini_d)]
    return por_dia


def linha(e: Dict[str, Any]) -> str:
    hora = "dia todo" if e["dia_todo"] else f"{e['inicio']:%H:%M}–{e['fim']:%H:%M}"
    extras = []
    ag = e.get("agenda", "")
    if ag and ag not in ("Pessoal", "Geral"):
        extras.append(f"🏷️ {ag}")
    if LUISA_EMAIL in [c.lower() for c in e.get("convidados", [])]:
        extras.append("👩 Luisa")
    outros = [c for c in e.get("convidados", []) if c and c.lower() != LUISA_EMAIL]
    if outros:
        extras.append(f"+{len(outros)}")
    if e.get("local"):
        extras.append(f"📍 {e['local']}")
    if e.get("pendente"):
        extras.append("⏳ local")
    return f"• {hora} {e['titulo']}" + (f" ({' · '.join(extras)})" if extras else "")


def agenda_dia(d: datetime.date, evs: Optional[List[Dict[str, Any]]] = None) -> str:
    evs = eventos_do_dia(d) if evs is None else evs
    return "\n".join(linha(e) for e in evs) if evs else "• livre"


def agenda_resumo(d: datetime.date, evs: Optional[List[Dict[str, Any]]] = None) -> str:
    evs = eventos_do_dia(d) if evs is None else evs
    if not evs:
        return "livre"
    nomes = ", ".join(f"{'' if e['dia_todo'] else e['inicio'].strftime('%Hh%M').replace('h00', 'h') + ' '}{e['titulo']}" for e in evs[:3])
    return f"{len(evs)} compromisso(s): {nomes}" + ("…" if len(evs) > 3 else "")


def tarefas_texto(hoje: datetime.date, ts: Optional[List[Dict[str, Any]]] = None) -> str:
    ts = [t for t in (google.listar_tarefas() if ts is None else ts) if not t["feita"]]
    atrasadas = [t for t in ts if t.get("data") and t["data"] < hoje.isoformat()]
    do_dia = [t for t in ts if t.get("data") == hoje.isoformat()]
    sem_data = [t for t in ts if not t.get("data")]
    out = []
    if do_dia:
        out += [f"• {t['titulo']}" for t in do_dia]
    if atrasadas:
        out += [f"• ⚠️ {t['titulo']} (era {t['data'][8:10]}/{t['data'][5:7]})" for t in atrasadas]
    if sem_data:
        out += [f"• {t['titulo']}" for t in sem_data[:5]] + ([f"• … +{len(sem_data) - 5} sem data"] if len(sem_data) > 5 else [])
    return "\n".join(out) if out else "• nenhuma pendente"


def _cab(hoje: datetime.date) -> str:
    return f"{DIAS[hoje.weekday()]} {hoje:%d/%m}"


def bom_dia() -> str:
    hoje = datetime.date.today()

    def _get_tempo() -> str:
        try:
            return "*🌤️ Florianópolis hoje*\n" + clima.detalhado(hoje)
        except Exception:
            return "*🌤️ Florianópolis*\n• previsão indisponível agora"

    def _get_mail() -> str:
        try:
            return gmail.texto_nao_lidos(5)
        except Exception:
            return ""

    def _get_bola() -> str:
        try:
            import esporte
            return esporte.resumo_favoritos(hoje)
        except Exception:
            return ""

    def _get_carreira() -> str:
        try:   # o resumo curto do CareerOps (vagas, comentários, conexões para aprovar) com o link
            import carreira
            return carreira.resumo()
        except Exception:
            return ""

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        f_ag = ex.submit(agenda_dia, hoje)
        f_tar = ex.submit(tarefas_texto, hoje)
        f_tempo = ex.submit(_get_tempo)
        f_mail = ex.submit(_get_mail)
        f_bola = ex.submit(_get_bola)
        f_car = ex.submit(_get_carreira)
        ag_txt, tar_txt, tempo, mail, bola = f_ag.result(), f_tar.result(), f_tempo.result(), f_mail.result(), f_bola.result()
        car = f_car.result()

    return (f"☀️ *Bom dia, Paulo!* — {_cab(hoje)}\n\n*🗓️ Agenda de hoje*\n{ag_txt}\n\n"
            f"*✅ Tarefas*\n{tar_txt}\n\n" + (mail + "\n\n" if mail else "")
            + (f"*⚽ Jogo hoje*\n{bola}\n\n" if bola else "") + (car + "\n\n" if car else "") + tempo)


def fim_do_dia() -> str:
    hoje = datetime.date.today()
    amanha = hoje + datetime.timedelta(days=1)
    por_dia = eventos_por_dia(hoje, 5)
    todas_tarefas = google.listar_tarefas(incluir_concluidas=True)
    feitas = [t for t in todas_tarefas if t["feita"] and t.get("concluida_em") == hoje.isoformat()]
    evs = por_dia.get(hoje, [])
    partes = [f"🌙 *Boa noite, Paulo!* — resumo de {_cab(hoje)}", "", "*📋 Hoje*"]
    partes += ([f"• ✅ {t['titulo']}" for t in feitas] or ["• nenhuma tarefa concluída registrada"])
    if evs:
        partes += ["*Compromissos do dia:*"] + [linha(e) for e in evs]
    pend = [t for t in todas_tarefas if not t["feita"]]
    partes += ["", f"*⏳ Ficaram pendentes ({len(pend)})*"] + ([f"• {t['titulo']}" for t in pend[:8]] or ["• nada"])
    try:
        import esporte
        partes += ["", "*📺 Hoje à noite na TV*", esporte.tv_hoje_a_noite(hoje)]
    except Exception:
        partes += ["", "*📺 Hoje à noite na TV*", "• programação indisponível agora"]
    try:
        t_am = clima.detalhado(amanha)
    except Exception:
        t_am = "• previsão indisponível agora"
    partes += ["", f"*📆 Amanhã — {_cab(amanha)} (detalhado)*", "*Agenda*", agenda_dia(amanha, por_dia.get(amanha, [])),
               "*Tempo*", t_am, "", "*🔭 Próximos 3 dias (resumo)*"]
    for k in (2, 3, 4):
        d = hoje + datetime.timedelta(days=k)
        try:
            tm = clima.resumo(d)
        except Exception:
            tm = "sem previsão"
        partes.append(f"• *{_cab(d)}* — {agenda_resumo(d, por_dia.get(d, []))} · {tm}")
    return "\n".join(partes)


def enviar(texto: str) -> bool:
    return lembretes._enviar(texto)
