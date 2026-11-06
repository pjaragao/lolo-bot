"""Google Maps Platform (Places API v1 + Routes API v2) para o Lolo.

Permite:
- Buscar lugares, restaurantes, lojas, clínicas, hotéis com nota, endereço, telefone, se está aberto agora, horários e link do Maps.
- Calcular rota, distância e tempo de deslocamento com trânsito em tempo real (Florianópolis/SC como contexto padrão).
"""
import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

# Centro de Florianópolis como referência padrão para buscas locais
FLORIPA_BIAS = {
    "circle": {
        "center": {"latitude": -27.5954, "longitude": -48.5480},
        "radius": 35000.0,
    }
}

MODOS = {
    "carro": "DRIVE", "dirigindo": "DRIVE", "drive": "DRIVE",
    "ape": "WALK", "a pe": "WALK", "a pé": "WALK", "caminhando": "WALK", "walk": "WALK",
    "bike": "BICYCLE", "bicicleta": "BICYCLE", "bicycle": "BICYCLE",
    "onibus": "TRANSIT", "ônibus": "TRANSIT", "transporte": "TRANSIT", "transit": "TRANSIT",
    "moto": "TWO_WHEELER",
}


def _key() -> str:
    return os.environ.get("GOOGLE_MAPS_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")


def _post(url: str, body: Dict[str, Any], field_mask: str) -> Dict[str, Any]:
    key = _key()
    if not key:
        raise RuntimeError("GOOGLE_MAPS_API_KEY não configurada.")
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": key,
            "X-Goog-FieldMask": field_mask,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        msg = exc.read().decode("utf-8", "replace")[:200]
        raise RuntimeError(f"Google Maps HTTP {exc.code}: {msg}") from None


def buscar_lugares(termo: str, limite: int = 5) -> str:
    """Busca estabelecimentos/endereços no Google Maps (Places API New)."""
    q = (termo or "").strip()
    if not q:
        return "Informe o que deseja buscar no Google Maps."
    # Se não mencionar cidade/estado, adiciona viés geográfico de Florianópolis
    body: Dict[str, Any] = {
        "textQuery": q,
        "languageCode": "pt-BR",
        "regionCode": "BR",
        "maxResultCount": max(1, min(int(limite or 5), 10)),
        "locationBias": FLORIPA_BIAS,
    }
    mask = (
        "places.displayName,places.formattedAddress,places.rating,places.userRatingCount,"
        "places.regularOpeningHours.openNow,places.regularOpeningHours.weekdayDescriptions,"
        "places.nationalPhoneNumber,places.websiteUri,places.googleMapsUri,places.priceLevel"
    )
    data = _post(PLACES_URL, body, mask)
    places = data.get("places") or []
    if not places:
        return f"Nenhum local encontrado no Google Maps para '{q}'."
    linhas: List[str] = [f"*📍 Google Maps — {q}*"]
    for p in places:
        nome = (p.get("displayName") or {}).get("text") or "Local"
        end = p.get("formattedAddress") or ""
        nota = p.get("rating")
        avals = p.get("userRatingCount")
        hours = p.get("regularOpeningHours") or {}
        aberto = hours.get("openNow")
        tel = p.get("nationalPhoneNumber") or ""
        uri = p.get("googleMapsUri") or ""
        site = p.get("websiteUri") or ""

        meta = []
        if nota:
            meta.append(f"⭐ {nota}" + (f" ({avals})" if avals else ""))
        if aberto is True:
            meta.append("🟢 Aberto agora")
        elif aberto is False:
            meta.append("🔴 Fechado agora")
        if tel:
            meta.append(f"📞 {tel}")

        bloco = f"• *{nome}*" + (f" — {' · '.join(meta)}" if meta else "")
        if end:
            bloco += f"\n  📍 {end}"
        if uri:
            bloco += f"\n  🗺️ {uri}"
        elif site:
            bloco += f"\n  🌐 {site}"
        linhas.append(bloco)
    return "\n\n".join(linhas)


def _norm_end(s: str) -> str:
    s = (s or "").strip()
    # Se o endereço for curto e não mencionar cidade/UF, assume Florianópolis, SC
    low = s.lower()
    if s and not any(c in low for c in ("florian", "fln", "são josé", "sao jose", "palhoça", "biguaçu", "navegantes", "itajaí", "itajai", "curitiba", "são paulo", " - sc", ", sc", "brasil")):
        return f"{s}, Florianópolis - SC"
    return s


def _fmt_duracao(dur_str: str) -> str:
    m = re.match(r"^(\d+)s$", str(dur_str or "").strip())
    if not m:
        return dur_str or "?"
    secs = int(m.group(1))
    mins = max(1, round(secs / 60))
    if mins < 60:
        return f"{mins} min"
    h, rm = divmod(mins, 60)
    return f"{h}h{rm:02d}min" if rm else f"{h}h"


def calcular_rota(origem: str, destino: str, modo: str = "carro") -> str:
    """Calcula tempo (com trânsito ao vivo) e distância entre dois locais via Google Routes API v2."""
    orig = _norm_end(origem)
    dest = _norm_end(destino)
    if not orig or not dest:
        return "Informe a origem e o destino para calcular a rota."
    travel_mode = MODOS.get((modo or "carro").strip().lower(), "DRIVE")
    body: Dict[str, Any] = {
        "origin": {"address": orig},
        "destination": {"address": dest},
        "travelMode": travel_mode,
        "languageCode": "pt-BR",
        "units": "METRIC",
        "computeAlternativeRoutes": True,
    }
    if travel_mode in ("DRIVE", "TWO_WHEELER"):
        body["routingPreference"] = "TRAFFIC_AWARE"
    mask = "routes.duration,routes.staticDuration,routes.distanceMeters,routes.description"
    data = _post(ROUTES_URL, body, mask)
    routes = data.get("routes") or []
    if not routes:
        return f"Não encontrei rota entre '{orig}' e '{dest}'."
    linhas = [f"*🚗 Rota: {origem} → {destino}*"]
    for i, r in enumerate(routes[:3]):
        km = (r.get("distanceMeters") or 0) / 1000.0
        dur = _fmt_duracao(r.get("duration") or "")
        est = _fmt_duracao(r.get("staticDuration") or "")
        via = r.get("description") or "rota principal"
        prefix = "1️⃣ *Mais rápida*" if i == 0 else f"{i + 1}️⃣ *Alternativa*"
        extra_transito = f" _(sem trânsito: {est})_" if est and est != dur and est != "?" else ""
        linhas.append(f"• {prefix} via *{via}*: *{dur}* ({km:.1f} km){extra_transito}")
    return "\n".join(linhas)
