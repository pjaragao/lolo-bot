"""Google Calendar e Google Tasks (REST + OAuth). Enquanto o Google não estiver conectado, tarefas e eventos ficam numa
fila local (locais.json) e são enviados sozinhos quando a conexão existir."""
import concurrent.futures
import datetime
import fcntl
import json
import os
import threading
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import pessoas

_token_lock = threading.Lock()

HOME = os.environ.get("HERMES_HOME", "/opt/data")
TOKEN_FILE = os.path.join(HOME, "google_token.json")
CLIENT_FILE = os.path.join(HOME, "google_client_secret.json")
LOCAL = os.path.join(HOME, "locais.json")
TZ = ZoneInfo("America/Sao_Paulo")
SCOPES = ["https://www.googleapis.com/auth/calendar", "https://www.googleapis.com/auth/tasks",
          "https://www.googleapis.com/auth/gmail.modify", "https://www.googleapis.com/auth/gmail.compose",
          "https://www.googleapis.com/auth/drive"]
CAL_BASE = "https://www.googleapis.com/calendar/v3"
CAL = f"{CAL_BASE}/calendars/primary/events"

# Agendas do Paulo (IDs reais no Google Calendar)
CALENDARS = {
    "pessoal": {"id": "primary", "label": "Pessoal", "colorId": "7"},
    "familia": {"id": "user@example.com", "label": "Family", "colorId": "3"},
    "trabalho": {"id": "user@example.com", "label": "Trabalho", "colorId": "10"},
    "sie": {"id": "user@example.com", "label": "SIÉ-Joy", "colorId": "6"},
    "viagem": {"id": "user@example.com", "label": "Viagem", "colorId": "7"},
}
ID_TO_CAT = {v["id"]: k for k, v in CALENDARS.items()}
ID_TO_CAT["user@example.com"] = "pessoal"

# Cores de eventos do Google Calendar (1 a 11)
COLOR_MAP = {
    "1": "1", "lavanda": "1", "azul claro": "1",
    "2": "2", "salvia": "2", "sálvia": "2", "verde claro": "2",
    "3": "3", "uva": "3", "roxo": "3", "lilas": "3", "lilás": "3", "familia": "3", "família": "3",
    "4": "4", "flamingo": "4", "rosa": "4",
    "5": "5", "banana": "5", "amarelo": "5",
    "6": "6", "tangerina": "6", "laranja": "6", "sie": "6", "sié": "6", "sié-joy": "6",
    "7": "7", "pavao": "7", "pavão": "7", "ciano": "7", "azul": "7", "turquesa": "7", "pessoal": "7", "viagem": "7",
    "8": "8", "grafite": "8", "cinza": "8",
    "9": "9", "mirtilo": "9", "azul escuro": "9",
    "10": "10", "manjericao": "10", "manjericão": "10", "verde": "10", "trabalho": "10",
    "11": "11", "tomate": "11", "vermelho": "11", "urgente": "11",
}


def resolve_cor(cor: Optional[str], categoria: str = "") -> Optional[str]:
    if cor:
        c = str(cor).strip().lower()
        if c in COLOR_MAP:
            return COLOR_MAP[c]
    return None


def resolve_agenda(agenda: Optional[str] = None, titulo: str = "", descricao: str = "") -> Tuple[str, str, str]:
    """Retorna (categoria, calendar_id, label)."""
    if agenda and "@" in str(agenda):
        cid = str(agenda).strip()
        cat = ID_TO_CAT.get(cid, "pessoal")
        return cat, cid, CALENDARS.get(cat, {}).get("label", cid)
    cat = pessoas.classificar_agenda(titulo, descricao, agenda)
    info = CALENDARS.get(cat, CALENDARS["pessoal"])
    return cat, info["id"], info["label"]


def _cal_url(calendar_id: str = "primary", suffix: str = "/events") -> str:
    cid = urllib.parse.quote(calendar_id or "primary", safe="")
    return f"{CAL_BASE}/calendars/{cid}{suffix}"


# --------------------------------------------------------------------------- auth
def conectado() -> bool:
    return os.path.isfile(TOKEN_FILE)


def _client() -> Dict[str, str]:
    raw = json.load(open(CLIENT_FILE, encoding="utf-8"))
    return raw.get("installed") or raw.get("web") or raw


def _access_token() -> str:
    with _token_lock:
        tok = json.load(open(TOKEN_FILE, encoding="utf-8"))
        if tok.get("access_token") and tok.get("expiry", 0) > datetime.datetime.now().timestamp() + 60:
            return tok["access_token"]
        c = _client()
        data = urllib.parse.urlencode({"client_id": c["client_id"], "client_secret": c["client_secret"],
                                       "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"}).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/token", data=data), timeout=20) as r:
                new = json.loads(r.read())
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 401):   # invalid_grant: the access expired or was revoked (an app in "Testing" lasts 7 days)
                avisar_reconexao(f"HTTP {exc.code}")
                raise AcessoExpirado("o acesso do Lolo ao Google expirou; mandei o link de reconexão no WhatsApp") from exc
            raise
        tok["access_token"] = new["access_token"]
        tok["expiry"] = datetime.datetime.now().timestamp() + int(new.get("expires_in", 3500))
        tmp = TOKEN_FILE + ".tmp"
        json.dump(tok, open(tmp, "w", encoding="utf-8"))
        os.replace(tmp, TOKEN_FILE)
        os.chmod(TOKEN_FILE, 0o600)
        try:
            if os.geteuid() == 0:
                st = os.stat(HOME)
                os.chown(TOKEN_FILE, st.st_uid, st.st_gid)
        except OSError:
            pass
        return tok["access_token"]


# --------------------------------------------------------------------------- reconexão pelo WhatsApp (2026-11-06)
REDIRECT = "http://localhost:1/"
AVISO_FILE = os.path.join(HOME, "google_reconexao.json")
AVISO_A_CADA_H = 6   # the broken access is told again at most every 6 hours, never on every call


class AcessoExpirado(RuntimeError):
    pass


def link_reconexao() -> str:
    c = _client()
    q = urllib.parse.urlencode({"client_id": c["client_id"], "redirect_uri": REDIRECT, "response_type": "code",
                                "scope": " ".join(SCOPES), "access_type": "offline", "prompt": "consent"})
    return "https://accounts.google.com/o/oauth2/v2/auth?" + q


def avisar_reconexao(motivo: str = "", agora: Optional[float] = None) -> bool:
    """Tells Paulo on WhatsApp, with the link, that Google refused Lolo's access. True when the message went out now."""
    import lembretes
    agora = agora or datetime.datetime.now().timestamp()
    try:
        ultimo = json.load(open(AVISO_FILE, encoding="utf-8")).get("avisado_em", 0)
    except (OSError, ValueError):
        ultimo = 0
    if agora - ultimo < AVISO_A_CADA_H * 3600:
        return False
    texto = ("⚠️ *Google desconectado* — o Google recusou o acesso do Lolo" + (f" ({motivo})" if motivo else "") +
             ". E-mails das vagas, agenda, tarefas e Drive estão parados.\n\n"
             f"1) Abra e aceite com a sua conta:\n{link_reconexao()}\n\n"
             "2) O navegador vai mostrar um erro em localhost:1. Copie o endereço inteiro da página e me mande aqui.")
    enviado = lembretes._enviar(texto)
    if enviado:
        json.dump({"avisado_em": agora, "motivo": motivo}, open(AVISO_FILE, "w", encoding="utf-8"))
    return enviado


def reconectar(endereco: str) -> str:
    """The address (or the code) Paulo sent back: exchanged for a new token, saved like ops/google_auth.py does."""
    raw = (endereco or "").strip()
    code = urllib.parse.parse_qs(urllib.parse.urlparse(raw).query).get("code", [raw])[0].strip()
    if not code or " " in code:
        return "Não achei o código no endereço. Mande o endereço inteiro que começa com http://localhost:1/?"
    c = _client()
    data = urllib.parse.urlencode({"code": code, "client_id": c["client_id"], "client_secret": c["client_secret"],
                                   "redirect_uri": REDIRECT, "grant_type": "authorization_code"}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/token", data=data), timeout=30) as r:
            tok = json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return (f"O Google recusou esse código (HTTP {exc.code}): ele vale só alguns minutos e uma vez. "
                f"Abra o link de novo e mande o endereço novo:\n{link_reconexao()}")
    if "refresh_token" not in tok:
        return f"O Google não mandou acesso permanente. Abra o link de novo e aceite tudo:\n{link_reconexao()}"
    tok["expiry"] = datetime.datetime.now().timestamp() + int(tok.get("expires_in", 3500))
    with _token_lock:
        tmp = TOKEN_FILE + ".tmp"
        json.dump(tok, open(tmp, "w", encoding="utf-8"))
        os.replace(tmp, TOKEN_FILE)
        os.chmod(TOKEN_FILE, 0o600)
    try:
        os.remove(AVISO_FILE)
    except OSError:
        pass
    return "✅ Google reconectado."


def _api(method: str, url: str, body: Any = None, params: Optional[Dict[str, Any]] = None) -> Any:
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"Authorization": f"Bearer {_access_token()}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Google HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:200]}") from None


# --------------------------------------------------------------------------- fila local
def _load() -> Dict[str, List[Dict[str, Any]]]:
    try:
        d = json.load(open(LOCAL, encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d.setdefault("eventos", [])
    d.setdefault("tarefas", [])
    return d


def _save(d: Dict[str, Any]) -> None:
    tmp = LOCAL + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, LOCAL)


def _locked(fn):
    def wrap(*a, **k):
        os.makedirs(HOME, exist_ok=True)
        with open(LOCAL + ".lock", "w") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            return fn(*a, **k)
    return wrap


@_locked
def _local_add(kind: str, item: Dict[str, Any]) -> None:
    d = _load()
    d[kind].append(item)
    _save(d)


# --------------------------------------------------------------------------- datas
def parse_dt(s: str) -> datetime.datetime:
    """Aceita 'AAAA-MM-DDTHH:MM', 'AAAA-MM-DD HH:MM' ou 'AAAA-MM-DD' (00:00)."""
    s = s.strip().replace(" ", "T")
    dt = datetime.datetime.fromisoformat(s if "T" in s else s + "T00:00")
    return dt.replace(tzinfo=TZ) if dt.tzinfo is None else dt.astimezone(TZ)


def _when(x: Dict[str, str]) -> datetime.datetime:
    return datetime.datetime.fromisoformat(x.get("dateTime") or x["date"] + "T00:00:00-03:00").astimezone(TZ)


def _norm_event(e: Dict[str, Any], pendente: bool = False, categoria: str = "pessoal", calendar_id: str = "primary") -> Dict[str, Any]:
    cat = categoria or ID_TO_CAT.get(calendar_id, "pessoal")
    label = CALENDARS.get(cat, CALENDARS["pessoal"])["label"]
    return {"id": e["id"], "recurringEventId": e.get("recurringEventId"), "titulo": e.get("summary", "(sem título)"),
            "inicio": _when(e["start"]), "fim": _when(e["end"]), "dia_todo": "date" in e["start"],
            "local": e.get("location", ""), "descricao": e.get("description", ""),
            "convidados": [a.get("email") for a in e.get("attendees", []) if not a.get("self")],
            "pendente": pendente, "link": e.get("htmlLink", ""), "categoria": cat, "agenda": label,
            "calendar_id": calendar_id, "cor": e.get("colorId")}


# --------------------------------------------------------------------------- eventos
_RRULE_DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
_PT_TO_BYDAY = {
    "seg": "MO", "segunda": "MO", "mo": "MO",
    "ter": "TU", "terca": "TU", "terça": "TU", "tu": "TU",
    "qua": "WE", "quarta": "WE", "we": "WE",
    "qui": "TH", "quinta": "TH", "th": "TH",
    "sex": "FR", "sexta": "FR", "fr": "FR",
    "sab": "SA", "sabado": "SA", "sábado": "SA", "sa": "SA",
    "dom": "SU", "domingo": "SU", "su": "SU",
}


def build_rrule(recorrencia: Optional[str], ini: datetime.datetime, dias_semana: Optional[str] = None,
                ate: Optional[str] = None) -> Optional[List[str]]:
    """Converte 'diario'/'semanal'/'mensal'/'anual' ou RRULE direto em lista ['RRULE:...'] do Google Calendar."""
    if not recorrencia:
        return None
    r = str(recorrencia).strip()
    if not r or r.lower() in ("nao", "não", "none", "unico", "único", "false"):
        return None
    if r.upper().startswith("RRULE:"):
        return [r.upper()]
    rl = r.lower()
    if rl in ("diario", "diário", "daily", "todos os dias", "todo dia"):
        rule = "RRULE:FREQ=DAILY"
    elif rl in ("dias uteis", "dias úteis", "weekdays", "seg a sex", "segunda a sexta"):
        rule = "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"
    elif rl in ("mensal", "monthly", "todo mes", "todo mês"):
        rule = f"RRULE:FREQ=MONTHLY;BYMONTHDAY={ini.day}"
    elif rl in ("anual", "yearly", "todo ano"):
        rule = "RRULE:FREQ=YEARLY"
    else:
        # Semanal (default quando pede recorrente ou passa dias da semana)
        bydays = []
        raw_days = dias_semana or (r if rl not in ("semanal", "weekly", "toda semana", "recorrente", "true", "1") else "")
        for tok in str(raw_days).replace(";", ",").split(","):
            t = tok.strip().lower().replace("-feira", "")
            if t in _PT_TO_BYDAY and _PT_TO_BYDAY[t] not in bydays:
                bydays.append(_PT_TO_BYDAY[t])
        if not bydays:
            bydays = [_RRULE_DAYS[ini.weekday()]]
        rule = f"RRULE:FREQ=WEEKLY;BYDAY={','.join(bydays)}"
    if ate:
        try:
            dt_ate = parse_dt(str(ate)[:10] + "T23:59:59")
            rule += f";UNTIL={dt_ate.astimezone(datetime.timezone.utc):%Y%m%dT%H%M%SZ}"
        except Exception:
            pass
    return [rule]


def criar_evento(titulo: str, inicio: str, fim: Optional[str] = None, duracao_min: int = 60, descricao: str = "",
                 local: str = "", convidados: Optional[List[str]] = None, dia_todo: bool = False,
                 agenda: Optional[str] = None, cor: Optional[str] = None,
                 recorrencia: Optional[str] = None, dias_semana: Optional[str] = None, ate: Optional[str] = None,
                 lembrete_min: Optional[int] = None) -> Dict[str, Any]:
    ini = parse_dt(inicio)
    end = parse_dt(fim) if fim else ini + datetime.timedelta(minutes=duracao_min or 60)
    conv = sorted({c.strip().lower() for c in (convidados or []) if c and "@" in c})
    cat, cal_id, label = resolve_agenda(agenda, titulo, descricao)
    cid_color = resolve_cor(cor, cat)
    body: Dict[str, Any] = {"summary": titulo, "description": descricao, "location": local}
    if cid_color:
        body["colorId"] = cid_color
    rrule = build_rrule(recorrencia, ini, dias_semana, ate)
    if rrule:
        body["recurrence"] = rrule
    if lembrete_min is not None:
        if int(lembrete_min) <= 0:
            body["reminders"] = {"useDefault": False, "overrides": []}
        else:
            body["reminders"] = {"useDefault": False, "overrides": [{"method": "popup", "minutes": int(lembrete_min)}]}
    if dia_todo:
        body["start"] = {"date": ini.date().isoformat()}
        body["end"] = {"date": (ini.date() + datetime.timedelta(days=1)).isoformat()}
    else:
        body["start"] = {"dateTime": ini.isoformat(), "timeZone": "America/Sao_Paulo"}
        body["end"] = {"dateTime": end.isoformat(), "timeZone": "America/Sao_Paulo"}
    if conv:
        body["attendees"] = [{"email": c} for c in conv]
    erro = ""
    if conectado():
        try:
            ev = _api("POST", _cal_url(cal_id), body, {"sendUpdates": "all"})
            return _norm_event(ev, categoria=cat, calendar_id=cal_id)
        except RuntimeError as exc:
            erro = str(exc)[:120]
    lid = "local-" + uuid.uuid4().hex[:8]
    _local_add("eventos", {"id": lid, "body": body, "calendar_id": cal_id, "categoria": cat, "erro": erro})
    return {"id": lid, "titulo": titulo, "inicio": ini, "fim": end, "dia_todo": dia_todo, "local": local,
            "descricao": descricao, "convidados": conv, "pendente": True, "erro": erro, "categoria": cat,
            "agenda": label, "calendar_id": cal_id, "cor": cid_color}


def listar_eventos(inicio: datetime.datetime, fim: datetime.datetime, agenda: Optional[str] = None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    cats = [resolve_agenda(agenda)[0]] if agenda else list(CALENDARS.keys())
    if conectado():
        try:
            _access_token()
        except Exception:
            pass

        def _fetch_cat(cat: str) -> List[Dict[str, Any]]:
            cal_id = CALENDARS[cat]["id"]
            try:
                data = _api("GET", _cal_url(cal_id), params={
                    "timeMin": inicio.isoformat(), "timeMax": fim.isoformat(),
                    "singleEvents": "true", "orderBy": "startTime", "maxResults": 250
                })
                return [_norm_event(e, categoria=cat, calendar_id=cal_id)
                        for e in data.get("items", []) if e.get("status") != "cancelled"]
            except RuntimeError:
                return []

        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(cats))) as ex:
            for items in ex.map(_fetch_cat, cats):
                for ev in items:
                    if ev["id"] not in seen:
                        seen.add(ev["id"])
                        out.append(ev)
    for it in _load()["eventos"]:      # ainda não sincronizados
        cat = it.get("categoria") or "pessoal"
        if agenda and cat not in cats:
            continue
        e = {"id": it["id"], **it["body"]}
        n = _norm_event(e, pendente=True, categoria=cat, calendar_id=it.get("calendar_id", "primary"))
        if inicio <= n["inicio"] < fim:
            out.append(n)
    return sorted(out, key=lambda e: e["inicio"])


def _find_event(eid: str = "", busca: str = "", data_ref: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
    """Localiza evento por id ou texto de busca em todas as agendas do Paulo. Retorna (calendar_id, raw_event)."""
    eid = (eid or "").strip()
    busca_low = (busca or "").strip().lower()
    dt_ref: Optional[datetime.date] = None
    if data_ref:
        try:
            dt_ref = parse_dt(str(data_ref)[:10]).date()
        except Exception:
            dt_ref = None
    if eid:
        for info in CALENDARS.values():
            try:
                ev = _api("GET", _cal_url(info["id"], f"/events/{urllib.parse.quote(eid, safe='')}"))
                if ev and ev.get("status") != "cancelled":
                    return info["id"], ev
            except RuntimeError:
                pass
        if not busca_low:
            busca_low = eid.lower()
    if busca_low:
        now = datetime.datetime.now(TZ) - datetime.timedelta(days=2)
        end = now + datetime.timedelta(days=60)
        if dt_ref:
            ref_dt = datetime.datetime.combine(dt_ref, datetime.time(0, 0), tzinfo=TZ)
            now = min(now, ref_dt - datetime.timedelta(days=1))
            end = max(end, ref_dt + datetime.timedelta(days=2))

        def _search_cal(info: Dict[str, str]) -> List[Tuple[str, Dict[str, Any]]]:
            try:
                data = _api("GET", _cal_url(info["id"]), params={
                    "timeMin": now.isoformat(), "timeMax": end.isoformat(),
                    "singleEvents": "true", "orderBy": "startTime", "maxResults": 250
                })
                return [(info["id"], e) for e in data.get("items", [])
                        if e.get("status") != "cancelled" and busca_low in (e.get("summary") or "").lower()]
            except RuntimeError:
                return []

        candidates: List[Tuple[str, Dict[str, Any]]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(CALENDARS)) as ex:
            for res in ex.map(_search_cal, CALENDARS.values()):
                candidates.extend(res)
        if candidates:
            if dt_ref:
                for cid, ev in candidates:
                    if _when(ev["start"]).date() == dt_ref:
                        return cid, ev
            candidates.sort(key=lambda pair: _when(pair[1]["start"]))
            return candidates[0]
    raise RuntimeError(f"Evento '{eid or busca}' não encontrado nas agendas.")


def editar_evento(eid: str = "", **campos: Any) -> str:
    if eid and eid.startswith("local-"):
        return "Evento ainda não sincronizado com o Google; cancele e crie de novo."
    busca = str(campos.pop("busca", "") or "")
    data_ref = campos.pop("data", None) or campos.get("inicio")
    apenas_esta = campos.pop("apenas_esta", None)
    cal_id, ev = _find_event(eid, busca, data_ref=data_ref)
    target_id = ev["id"]
    # Decide se edita o evento-mestre da série recorrente ou apenas uma ocorrência específica
    edit_master = (
        ev.get("recurringEventId")
        and apenas_esta is not True
        and (apenas_esta is False or bool(campos.get("recorrencia")) or (not campos.get("inicio") and not data_ref))
    )
    if edit_master:
        try:
            master = _api("GET", _cal_url(cal_id, f"/events/{urllib.parse.quote(ev['recurringEventId'], safe='')}"))
            if master and master.get("status") != "cancelled":
                ev = master
                target_id = master["id"]
        except RuntimeError:
            pass
    if campos.get("titulo"):
        ev["summary"] = campos["titulo"]
    if campos.get("descricao") is not None:
        ev["description"] = campos["descricao"]
    if campos.get("local") is not None:
        ev["location"] = campos["local"]
    if campos.get("inicio"):
        ini = parse_dt(campos["inicio"])
        dur = _when(ev["end"]) - _when(ev["start"])
        if edit_master and ev.get("recurrence"):
            # No mestre recorrente, preserva a data de início da série se só mudou o horário
            m_start = _when(ev["start"])
            ini = datetime.datetime.combine(m_start.date(), ini.timetz())
        fim = parse_dt(campos["fim"]) if campos.get("fim") else ini + dur
        ev["start"] = {"dateTime": ini.isoformat(), "timeZone": "America/Sao_Paulo"}
        ev["end"] = {"dateTime": fim.isoformat(), "timeZone": "America/Sao_Paulo"}
    if campos.get("convidados"):
        have = {a["email"].lower() for a in ev.get("attendees", []) if a.get("email")}
        ev["attendees"] = ev.get("attendees", []) + [{"email": c} for c in campos["convidados"] if c.lower() not in have]
    if campos.get("remover_convidados"):
        rem = {c.lower() for c in campos["remover_convidados"]}
        ev["attendees"] = [a for a in ev.get("attendees", []) if (a.get("email") or "").lower() not in rem]
    if campos.get("cor"):
        cid_color = resolve_cor(campos["cor"])
        if cid_color:
            ev["colorId"] = cid_color
    elif campos.get("agenda"):
        cat_dest, _, _ = resolve_agenda(campos["agenda"])
        dest_color = CALENDARS.get(cat_dest, {}).get("colorId")
        if dest_color:
            ev["colorId"] = dest_color
    if campos.get("recorrencia"):
        rrule = build_rrule(campos["recorrencia"], _when(ev["start"]), campos.get("dias_semana"), campos.get("ate"))
        if rrule:
            ev["recurrence"] = rrule
    if campos.get("lembrete_min") is not None:
        lm = int(campos["lembrete_min"])
        ev["reminders"] = {"useDefault": False, "overrides": [] if lm <= 0 else [{"method": "popup", "minutes": lm}]}
    _api("PUT", _cal_url(cal_id, f"/events/{urllib.parse.quote(target_id, safe='')}"), ev, {"sendUpdates": "all"})
    if campos.get("agenda"):
        cat_dest, dest_id, _ = resolve_agenda(campos["agenda"])
        if dest_id != cal_id:
            try:
                _api("POST", _cal_url(cal_id, f"/events/{urllib.parse.quote(target_id, safe='')}/move"),
                     params={"destination": dest_id})
            except RuntimeError:
                # Se não puder mover (ex.: organizador externo ou instância isolada), mantém a cor correspondente
                fallback_color = CALENDARS.get(cat_dest, {}).get("colorId")
                if fallback_color:
                    _api("PATCH", _cal_url(cal_id, f"/events/{urllib.parse.quote(target_id, safe='')}"),
                         {"colorId": fallback_color})
    return "ok"


@_locked
def cancelar_evento(eid: str = "", busca: str = "", data_ref: Optional[str] = None,
                    apenas_esta: Optional[bool] = None) -> str:
    if eid and eid.startswith("local-"):
        d = _load()
        d["eventos"] = [e for e in d["eventos"] if e["id"] != eid]
        _save(d)
        return "ok"
    cal_id, ev = _find_event(eid, busca, data_ref=data_ref)
    target_id = ev["recurringEventId"] if (apenas_esta is False and ev.get("recurringEventId")) else ev["id"]
    _api("DELETE", _cal_url(cal_id, f"/events/{urllib.parse.quote(target_id, safe='')}"), params={"sendUpdates": "all"})
    return "ok"


def listar_agendas() -> str:
    linhas = [
        "• *Pessoal* (azul) — saúde, treinos (Academia), rotina individual",
        "• *Family* (roxo) — família, filhos (Paulinho/JJ, Tata), compromissos de casal",
        "• *Trabalho* (verde) — reuniões profissionais (Teams/Meet), entrevistas, loteamentos, fornecedores",
        "• *SIÉ-Joy* (laranja) — compromissos exclusivos da loja SIÉ JOY",
        "• *Viagem* (ciano/turquesa) — voos, hotéis, deslocamentos e férias",
    ]
    return "\n".join(linhas)


# --------------------------------------------------------------------------- tarefas (Google Tasks, várias listas)
TASKS_API = "https://tasks.googleapis.com/tasks/v1"
_PADRAO = ("", "@default", "padrao", "lista padrao", "principal", "minhas tarefas", "my tasks")
_TODAS = ("todas", "todas as listas", "tudo", "*")


def _sem_acento(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().strip()


def _tasks_url(lista_id: str = "@default") -> str:
    return f"{TASKS_API}/lists/{urllib.parse.quote(lista_id or '@default', safe='@')}/tasks"


def _due(data: str) -> str:
    return parse_dt(data).date().isoformat() + "T00:00:00.000Z"


def listar_listas() -> List[Dict[str, str]]:
    r = _api("GET", f"{TASKS_API}/users/@me/lists", params={"maxResults": 100})
    padrao = _api("GET", f"{TASKS_API}/users/@me/lists/@default").get("id")
    return [{"id": x["id"], "titulo": x.get("title", ""), "padrao": x["id"] == padrao} for x in r.get("items", [])]


def resolve_lista(lista: Optional[str]) -> Tuple[str, str]:
    """Nome (parcial, sem acento) ou id da lista → (id, título). Vazio = lista padrão."""
    alvo = (lista or "").strip()
    ls = listar_listas()
    if _sem_acento(alvo) in _PADRAO:
        p = next((x for x in ls if x["padrao"]), None)
        return (p["id"], p["titulo"]) if p else ("@default", "padrão")
    for x in ls:
        if x["id"] == alvo:
            return x["id"], x["titulo"]
    n = _sem_acento(alvo)
    achadas = [x for x in ls if _sem_acento(x["titulo"]) == n] or [x for x in ls if n in _sem_acento(x["titulo"])]
    if len(achadas) == 1:
        return achadas[0]["id"], achadas[0]["titulo"]
    nomes = ", ".join(x["titulo"] for x in ls) or "nenhuma"
    if achadas:
        raise RuntimeError(f"Mais de uma lista combina com '{alvo}': {', '.join(x['titulo'] for x in achadas)}.")
    raise RuntimeError(f"Lista '{alvo}' não existe no Google Tasks. Listas: {nomes}. Para criar, use 'lista_criar'.")


def criar_lista(titulo: str) -> Dict[str, str]:
    titulo = (titulo or "").strip()
    if not titulo:
        raise RuntimeError("Informe o nome da lista.")
    for x in listar_listas():
        if _sem_acento(x["titulo"]) == _sem_acento(titulo):
            return {"id": x["id"], "titulo": x["titulo"], "ja_existia": True}
    r = _api("POST", f"{TASKS_API}/users/@me/lists", {"title": titulo})
    return {"id": r["id"], "titulo": r.get("title", titulo), "ja_existia": False}


def renomear_lista(lista: str, novo_titulo: str) -> Dict[str, str]:
    if not (novo_titulo or "").strip():
        raise RuntimeError("Informe o novo nome da lista.")
    lid, _ = resolve_lista(lista)
    r = _api("PATCH", f"{TASKS_API}/users/@me/lists/{urllib.parse.quote(lid, safe='')}", {"title": novo_titulo.strip()})
    return {"id": r["id"], "titulo": r.get("title", novo_titulo)}


def criar_tarefa(titulo: str, notas: str = "", data: Optional[str] = None, lista: Optional[str] = None) -> Dict[str, Any]:
    erro = ""
    if conectado():
        lid, lnome = resolve_lista(lista)          # lista inexistente é erro do pedido: não vai para a fila local
        try:
            body: Dict[str, Any] = {"title": titulo, "notes": notas}
            if data:
                body["due"] = _due(data)
            t = _api("POST", _tasks_url(lid), body)
            return {"id": t["id"], "titulo": titulo, "data": data, "lista": lnome, "pendente": False}
        except RuntimeError as exc:
            erro = str(exc)[:120]
    lid = "local-" + uuid.uuid4().hex[:8]
    _local_add("tarefas", {"id": lid, "titulo": titulo, "notas": notas, "data": data, "feita": False, "erro": erro,
                           "lista": (lista or "").strip()})
    return {"id": lid, "titulo": titulo, "data": data, "lista": (lista or "").strip(), "pendente": True}


def _tarefas_da_lista(lid: str, lnome: str, incluir_concluidas: bool) -> List[Dict[str, Any]]:
    data = _api("GET", _tasks_url(lid), params={"showCompleted": str(incluir_concluidas).lower(),
                                                 "showHidden": str(incluir_concluidas).lower(), "maxResults": 100})
    return [{"id": t["id"], "titulo": t.get("title", ""), "data": (t.get("due") or "")[:10] or None,
             "feita": t.get("status") == "completed", "concluida_em": (t.get("completed") or "")[:10],
             "notas": t.get("notes", ""), "lista": lnome, "lista_id": lid, "pendente": False}
            for t in data.get("items", [])]


def listar_tarefas(incluir_concluidas: bool = False, lista: Optional[str] = None) -> List[Dict[str, Any]]:
    """Sem lista = só a lista padrão (é o que o bom dia/fim do dia mostram); lista='todas' percorre todas."""
    out: List[Dict[str, Any]] = []
    todas = _sem_acento(lista or "") in _TODAS
    if conectado():
        if todas:
            for x in listar_listas():
                out += _tarefas_da_lista(x["id"], x["titulo"], incluir_concluidas)
        elif lista:
            lid, lnome = resolve_lista(lista)
            out += _tarefas_da_lista(lid, lnome, incluir_concluidas)
        else:
            try:
                out += _tarefas_da_lista("@default", "", incluir_concluidas)
            except RuntimeError:
                pass
    for t in _load()["tarefas"]:
        if (todas or _sem_acento(t.get("lista", "")) == _sem_acento(lista or "")) and (incluir_concluidas or not t.get("feita")):
            out.append({"id": t["id"], "titulo": t["titulo"], "data": t.get("data"), "feita": t.get("feita", False),
                        "concluida_em": t.get("concluida_em", ""), "notas": t.get("notas", ""),
                        "lista": t.get("lista", ""), "pendente": True})
    return out


def _achar_tarefa(tid: str, busca_low: str, lista: Optional[str] = None,
                  incluir_concluidas: bool = False) -> Tuple[str, Dict[str, Any]]:
    """Acha a tarefa pelo id ou por parte do título; sem lista, procura em todas (a padrão primeiro)."""
    if lista:
        listas = [resolve_lista(lista)[0]]
    else:
        ls = listar_listas()
        listas = [x["id"] for x in sorted(ls, key=lambda x: not x["padrao"])] or ["@default"]
    if tid:
        for lid in listas:
            try:
                return lid, _api("GET", f"{_tasks_url(lid)}/{urllib.parse.quote(tid, safe='')}")
            except RuntimeError:
                continue
        busca_low = busca_low or tid.lower()
    if busca_low:
        for lid in listas:
            for t in _tarefas_da_lista(lid, "", incluir_concluidas):
                if busca_low in (t.get("titulo") or "").lower():
                    return lid, _api("GET", f"{_tasks_url(lid)}/{t['id']}")
    raise RuntimeError(f"Tarefa '{tid or busca_low}' não encontrada no Google Tasks.")


@_locked
def editar_tarefa(tid: str = "", busca: str = "", titulo: Optional[str] = None, notas: Optional[str] = None,
                  data: Optional[str] = None, lista: Optional[str] = None) -> Dict[str, Any]:
    tid = (tid or "").strip()
    busca_low = (busca or "").strip().lower()
    if tid.startswith("local-") or (not tid and busca_low):
        d = _load()
        for t in d["tarefas"]:
            if (tid and t["id"] == tid) or (not tid and busca_low and busca_low in (t.get("titulo") or "").lower()):
                if titulo:
                    t["titulo"] = titulo
                if notas is not None:
                    t["notas"] = notas
                if data:
                    t["data"] = data
                _save(d)
                return t
        if tid.startswith("local-"):
            raise RuntimeError(f"Tarefa local '{tid}' não encontrada.")
    lid, target = _achar_tarefa(tid, busca_low, lista)
    if titulo:
        target["title"] = titulo
    if notas is not None:
        target["notes"] = notas
    if data:
        target["due"] = _due(data)
    res = _api("PATCH", f"{_tasks_url(lid)}/{target['id']}", target)
    return {"id": res["id"], "titulo": res.get("title", ""), "notas": res.get("notes", ""),
            "data": (res.get("due") or "")[:10] or None}


@_locked
def concluir_tarefa(tid: str = "", busca: str = "", lista: Optional[str] = None) -> str:
    tid = (tid or "").strip()
    busca_low = (busca or "").strip().lower()
    if tid.startswith("local-") or (not tid and busca_low):
        d = _load()
        for t in d["tarefas"]:
            if not t.get("feita") and ((tid and t["id"] == tid) or (not tid and busca_low in (t.get("titulo") or "").lower())):
                t["feita"], t["concluida_em"] = True, datetime.date.today().isoformat()
                _save(d)
                return "ok"
        if tid.startswith("local-"):
            return "ok"
    lid, target = _achar_tarefa(tid, busca_low, lista)
    _api("PATCH", f"{_tasks_url(lid)}/{target['id']}", {"status": "completed"})
    return "ok"


def mover_tarefa(tid: str = "", busca: str = "", destino: str = "", origem: Optional[str] = None) -> Dict[str, Any]:
    """Move a tarefa para outra lista (tasks.move com destinationTasklist; se a API recusar, recria e apaga a original)."""
    if not (destino or "").strip():
        raise RuntimeError("Informe a lista de destino.")
    did, dnome = resolve_lista(destino)
    lid, t = _achar_tarefa((tid or "").strip(), (busca or "").strip().lower(), origem, incluir_concluidas=True)
    if lid == did:
        return {"id": t["id"], "titulo": t.get("title", ""), "lista": dnome, "ja_estava": True}
    try:
        res = _api("POST", f"{_tasks_url(lid)}/{t['id']}/move", {}, {"destinationTasklist": did})
    except RuntimeError:
        novo = {k: t[k] for k in ("title", "notes", "due", "status") if t.get(k)}
        res = _api("POST", _tasks_url(did), novo)
        _api("DELETE", f"{_tasks_url(lid)}/{t['id']}")
    return {"id": res["id"], "titulo": res.get("title", ""), "lista": dnome, "ja_estava": False}


@_locked
def sincronizar() -> str:
    """Envia ao Google o que ficou na fila local (quando conectado)."""
    d = _load()
    if not conectado():
        return (f"Google não conectado; {len(d['eventos'])} evento(s) e "
                f"{len([t for t in d['tarefas'] if not t.get('feita')])} tarefa(s) aguardando.")
    ok_e = ok_t = 0
    rest_e, rest_t = [], []
    for e in d["eventos"]:
        try:
            cal_id = e.get("calendar_id") or "primary"
            _api("POST", _cal_url(cal_id), e["body"], {"sendUpdates": "all"})
            ok_e += 1
        except RuntimeError:
            rest_e.append(e)
    for t in d["tarefas"]:
        if t.get("feita"):
            continue
        try:
            body: Dict[str, Any] = {"title": t["titulo"], "notes": t.get("notas", "")}
            if t.get("data"):
                body["due"] = _due(t["data"])
            _api("POST", _tasks_url(resolve_lista(t.get("lista"))[0]), body)
            ok_t += 1
        except RuntimeError:
            rest_t.append(t)
    d["eventos"], d["tarefas"] = rest_e, rest_t
    _save(d)
    return f"Sincronizados: {ok_e} evento(s), {ok_t} tarefa(s); restam {len(rest_e) + len(rest_t)}."
