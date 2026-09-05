import base64
import os
import re
import unicodedata
from typing import Dict, Tuple, Optional

import requests

STREET_WORDS = (
    "calle", "carrer", "avenida", "av.", "paseo", "passatge", "pasaje",
    "plaza", "plaça", "carretera", "ctra", "camino", "ronda", "travesia",
    "travesía", "urbanizacion", "urbanización"
)


def _clean(s):
    return re.sub(r"\s+", " ", (s or "").strip())


def _ascii(s):
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def detect_carrier(text: str, raw_code: str = "") -> Tuple[str, float, str]:
    t = _ascii(text).lower()
    code = (raw_code or "").upper().strip()
    if "imile" in t or "i mile" in t or re.search(r"\bSHN\b", text or "", re.I):
        return "imile", 0.98, "Marca/formato iMile detectado"
    if "ecoscooting" in t or "eco scooting" in t or "urban delivery" in t:
        return "ecoscooting", 0.98, "Marca/formato Ecoscooting detectado"
    if "tipsa" in t or "alicante centro" in t or "alicante centre" in t:
        return "agencia", 0.90, "Formato agencia/centro detectado"
    if re.search(r"\bMAD-ALC\d", (text or "").upper()):
        return "ecoscooting", 0.78, "Código de hub MAD-ALC"
    if re.search(r"\bALC7\b", (text or "").upper()) and re.search(r"\bR-\d+\b", (text or "").upper()):
        return "imile", 0.76, "Zona ALC7 + ruta R-*"
    if code.startswith("LP") or code.startswith("AP00"):
        return "ecoscooting", 0.70, "Patrón de tracking Ecoscooting"
    return "unknown", 0.25, "Operadora no identificada"


def _lines(text):
    return [_clean(x) for x in (text or "").replace("\r", "\n").split("\n") if _clean(x)]


def _pick_postal(text):
    hits = re.findall(r"(?<!\d)(0\d{4})(?!\d)", text or "")
    return hits[0] if hits else ""


def _pick_weight(text):
    pats = [
        r"(?:claim\s*weight|g\.?\s*w\.?|peso|weight)\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*(?:kg)?",
        r"(\d+(?:[.,]\d+)?)\s*kg\b",
    ]
    for p in pats:
        m = re.search(p, _ascii(text).lower())
        if m:
            try:
                return float(m.group(1).replace(",", "."))
            except Exception:
                pass
    return None


def _pick_qty(text):
    for p in [
        r"\bQty\s*[:=]?\s*(\d+)\b",
        r"\bCantidad\s*[:=]?\s*(\d+)\b",
        r"\bPcs\s*[:=]?\s*(\d+)\b",
    ]:
        m = re.search(p, text or "", re.I)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass
    return 1


def _pick_phone(text):
    compact = re.sub(r"[\s-]", "", text or "")
    m = re.search(r"(?<!\d)([6789]\d{8})(?!\d)", compact)
    return m.group(1) if m else ""


def _pick_route_fields(text):
    up = (text or "").upper()
    zone = ""
    route = ""
    for p in [r"\b(ALIC\d+[A-Z]?)\b", r"\b(ALC\d+[A-Z]?)\b"]:
        m = re.search(p, up)
        if m:
            zone = m.group(1)
            break
    m = re.search(r"\b(R-\d+)\b", up)
    if m:
        route = m.group(1)
    return zone, route


def _candidate_tracking(text, raw_code=""):
    raw_code = _clean(raw_code)
    if raw_code:
        return raw_code
    candidates = re.findall(r"\b[A-Z]{1,4}\d[A-Z0-9]{8,26}\b|\b\d{11,18}\b", (text or "").upper())
    filtered = [x for x in candidates if not x.startswith(("03013", "03700"))]
    if not filtered:
        return ""
    filtered.sort(key=lambda x: ((x.startswith("LP") or x.startswith("AP")), len(x)), reverse=True)
    return filtered[0]


def _address_candidate(text, carrier):
    ls = _lines(text)
    for i, line in enumerate(ls):
        low = _ascii(line).lower()
        if any(w in low for w in STREET_WORDS):
            addr = [line]
            if i + 1 < len(ls):
                nxt = ls[i + 1]
                nl = _ascii(nxt).lower()
                # Solo anexar la línea siguiente si parece complemento de piso/puerta.
                if not any(k in nl for k in ("alicante", "alacant", "madrid", "spain", "esp", "qty", "normal", "lp")):
                    if len(nxt) < 55 and (re.search(r"\d", nxt) or any(k in nl for k in ("piso", "puerta", "portal", "escalera", "bar"))):
                        addr.append(nxt)
            return ", ".join(addr)
    if carrier == "imile":
        for i, line in enumerate(ls):
            low = _ascii(line).lower()
            if ("alicante" in low or "denia" in low) and i >= 2:
                prev = ls[max(0, i - 2):i]
                useful = [x for x in prev if not re.fullmatch(r"[A-Z0-9 -]{2,12}", x)]
                if useful:
                    return ", ".join(useful[-2:])
    return ""


def _recipient_candidate(text, address):
    ls = _lines(text)
    if address:
        first = address.split(",")[0].strip()
        for i, line in enumerate(ls):
            if line == first and i > 0:
                prev = ls[i - 1]
                low = _ascii(prev).lower()
                if not any(k in low for k in ("sender", "delivery", "alicante", "spain", "esp", "ship date")):
                    if 2 <= len(prev.split()) <= 6 and not re.search(r"\d{4,}", prev):
                        return prev
    return ""


def parse_label_text(text: str, raw_code: str = "") -> Dict:
    carrier, carrier_conf, carrier_reason = detect_carrier(text, raw_code)
    postal = _pick_postal(text)
    zone, route = _pick_route_fields(text)
    address = _address_candidate(text, carrier)
    recipient = _recipient_candidate(text, address)
    tracking = _candidate_tracking(text, raw_code)
    phone = _pick_phone(text)
    weight = _pick_weight(text)
    qty = _pick_qty(text)
    city = ""
    t = _ascii(text).lower()
    if "denia" in t:
        city = "Dénia"
    elif "alicante" in t or "alacant" in t:
        city = "Alicante"

    full_address = address
    if full_address and postal and postal not in full_address:
        full_address = f"{full_address}, {postal}"
    if full_address and city and city.lower() not in _ascii(full_address).lower():
        full_address = f"{full_address}, {city}, España"

    score = 0.0
    score += 0.22 if carrier != "unknown" else 0
    score += 0.18 if tracking else 0
    score += 0.28 if address else 0
    score += 0.12 if postal else 0
    score += 0.08 if recipient else 0
    score += 0.06 if zone or route else 0
    score += 0.06 if weight is not None or qty is not None else 0
    score = min(0.99, score)
    intake_status = "ready" if tracking and address and score >= 0.62 else "review"

    return {
        "carrier": carrier,
        "carrier_reason": carrier_reason,
        "carrier_confidence": carrier_conf,
        "tracking_code": tracking,
        "barcode": raw_code or tracking,
        "recipient_name": recipient,
        "phone": phone,
        "address": full_address or "",
        "postal_code": postal,
        "city": city,
        "route_zone": zone,
        "route_code": route,
        "weight_kg": weight,
        "quantity": qty,
        "intake_confidence": round(score, 2),
        "intake_status": intake_status,
    }


def google_vision_text(image_bytes: bytes) -> Tuple[Optional[str], Optional[str]]:
    if not image_bytes:
        return None, "Imagen vacía"
    project = (os.environ.get("GOOGLE_CLOUD_PROJECT") or "").strip()
    key = (os.environ.get("GOOGLE_VISION_API_KEY") or "").strip()
    payload = {
        "requests": [{
            "image": {"content": base64.b64encode(image_bytes).decode("ascii")},
            "features": [{"type": "TEXT_DETECTION", "maxResults": 1}],
        }]
    }
    try:
        headers = {"Content-Type": "application/json"}
        if key:
            url = f"https://vision.googleapis.com/v1/images:annotate?key={key}"
        else:
            cred_path = (os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or "").strip()
            if not (project and cred_path):
                return None, "OCR no configurado"
            from google.oauth2 import service_account
            from google.auth.transport.requests import Request as GoogleAuthRequest
            creds = service_account.Credentials.from_service_account_file(
                cred_path, scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            creds.refresh(GoogleAuthRequest())
            headers["Authorization"] = f"Bearer {creds.token}"
            url = f"https://eu-vision.googleapis.com/v1/projects/{project}/locations/eu/images:annotate"
        r = requests.post(url, headers=headers, json=payload, timeout=25)
        if not r.ok:
            return None, f"Vision HTTP {r.status_code}: {r.text[:220]}"
        data = r.json()
        resp = (data.get("responses") or [{}])[0]
        if resp.get("error"):
            return None, str(resp["error"])
        ann = resp.get("textAnnotations") or []
        if ann:
            return ann[0].get("description", ""), None
        return None, "No se detectó texto"
    except Exception as exc:
        return None, f"Vision error: {exc}"
