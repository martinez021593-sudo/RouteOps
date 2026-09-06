import base64
import os
import re
import unicodedata
from typing import Dict, Tuple, Optional, List

import requests

# RouteOps V0.3.1.3 — carrier-specific label profiles.
# The OCR text is never persisted by this module; only normalized operational fields are returned.

STREET_WORDS = (
    "calle", "carrer", "avenida", "av.", "av ", "paseo", "passatge", "pasaje",
    "plaza", "plaça", "carretera", "ctra", "camino", "ronda", "travesia",
    "travesía", "urbanizacion", "urbanización", "via", "camí", "cami",
)


def _clean(s):
    return re.sub(r"\s+", " ", (s or "").strip())


def _ascii(s):
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def _lines(text):
    return [_clean(x) for x in (text or "").replace("\r", "\n").split("\n") if _clean(x)]


def _flat(text):
    return _ascii(_clean(text)).lower()


def _compact_upper(text):
    return re.sub(r"[^A-Z0-9]", "", _ascii(text or "").upper())


def _looks_code(line):
    s = _clean(line)
    if not s: return True
    if re.fullmatch(r"[A-Z0-9_./-]{2,40}", _ascii(s).upper()): return True
    if len(re.sub(r"\D", "", s)) >= max(8, int(len(s) * .70)): return True
    return False


def _contains_city(line):
    s = _ascii(line).lower()
    return any(x in s for x in ("alicante", "alacant", "denia", "denia,"))


def detect_carrier(text: str, raw_code: str = "") -> Tuple[str, float, str]:
    t = _flat(text)
    up = _ascii(text or "").upper()
    compact = _compact_upper(text)
    code = _compact_upper(raw_code)

    # iMile: logo can OCR as iMile / i Mile / imlle. SHN + ALC7 + R-3 is a strong profile fingerprint.
    imile_signals = 0
    if re.search(r"\bi\s*m[i1l]\s*[l1i]e\b", t, re.I) or "IMILEDELIVERY" in compact: imile_signals += 3
    if re.search(r"\bSHN\b", up): imile_signals += 2
    if re.search(r"\bAL\s*C\s*7\b", up): imile_signals += 2
    if re.search(r"\bR\s*[-–]?\s*3\b", up): imile_signals += 1
    if "BAT&CATEGORY" in compact or "BATCATEGORY" in compact: imile_signals += 1
    if imile_signals >= 4:
        return "imile", min(.99, .68 + imile_signals*.045), "Perfil iMile/SHN"

    # Ecoscooting: multiple redundant markers so an imperfect logo OCR is fine.
    eco_signals = 0
    if re.search(r"eco\s*scoot", t) or "ECOSCOOTING" in compact: eco_signals += 3
    if re.search(r"\bMAD\s*[-_]\s*ALC\s*1\b", up): eco_signals += 2
    if re.search(r"\bLP[A-Z0-9]{12,26}\b", up): eco_signals += 2
    if re.search(r"\bALIC\s*\d{2}[A-Z]\b", up): eco_signals += 1
    if "CLAIMWEIGHT" in compact: eco_signals += 1
    if code.startswith("LP") or code.startswith("AP00"): eco_signals += 1
    if eco_signals >= 4:
        return "ecoscooting", min(.99, .68 + eco_signals*.04), "Perfil Ecoscooting"

    # TIPSA / agency family. Some labels carry customer/partner branding but keep the same depot template.
    tipsa_signals = 0
    if "TIPSA" in compact: tipsa_signals += 3
    if re.search(r"ALICANTE\s+CENTRO\s*10", up): tipsa_signals += 3
    for marker in ("REEMBOLSO", "BULTOS", "PPEDIDOS", "CARGOA", "CTA", "RTE", "DES"):
        if marker in compact: tipsa_signals += 1
    if re.search(r"\b0?3\d{3}\s*[/|]\s*\d{1,2}\s*HORAS\b", up): tipsa_signals += 1
    if tipsa_signals >= 5:
        return "tipsa", min(.98, .64 + tipsa_signals*.035), "Perfil TIPSA/agencia Alicante Centro"

    return "unknown", 0.25, "Operadora no identificada"


def _pick_postal(text, carrier="unknown"):
    # Prefer stand-alone Spanish CPs. Avoid picking digits embedded in a barcode.
    hits = re.findall(r"(?<!\d)(0\d{4})(?!\d)", text or "")
    if not hits: return ""
    if carrier == "imile" and "03700" in hits: return "03700"
    if carrier == "ecoscooting" and "03013" in hits: return "03013"
    return hits[0]


def _pick_city(text, carrier="unknown"):
    t = _flat(text)
    if "denia" in t:
        return "Dénia"
    if "alicante" in t or "alacant" in t:
        return "Alicante"
    return ""


def _pick_weight(text, carrier="unknown"):
    s = _ascii(text).lower()
    pats = [
        r"claim\s*weight\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*kg",
        r"g\.?\s*w\.?\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*(?:kg)?",
        r"(?:peso|weight)\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*kg",
        r"(\d+(?:[.,]\d+)?)\s*kg\b",
    ]
    for p in pats:
        m = re.search(p, s)
        if m:
            try: return float(m.group(1).replace(",", "."))
            except Exception: pass
    return None


def _pick_qty(text, carrier="unknown"):
    s = text or ""
    pats = []
    if carrier == "tipsa":
        pats += [r"\bBULTOS\s*[:=]?\s*(\d+)\b"]
    pats += [r"\bQty\s*[:=]?\s*(\d+)\b", r"\bCantidad\s*[:=]?\s*(\d+)\b"]
    for p in pats:
        m = re.search(p, s, re.I)
        if m:
            try: return max(1, int(m.group(1)))
            except Exception: pass
    return 1


def _pick_phone(text):
    compact = re.sub(r"[\s-]", "", text or "")
    # Do not manufacture a number from masked Ecoscooting phone strings.
    if "*" in compact:
        return ""
    m = re.search(r"(?<!\d)([6789]\d{8})(?!\d)", compact)
    return m.group(1) if m else ""


def _route_fields(text, carrier):
    up = _ascii(text or "").upper()
    compact = _compact_upper(text)
    zone = route = ""
    if carrier == "imile":
        m = re.search(r"\bAL\s*C\s*([0-9A-Z]{1,3})\b", up)
        if m: zone = "ALC" + re.sub(r"\s+", "", m.group(1))
        m = re.search(r"\bR\s*[-–]?\s*(\d{1,3})\b", up)
        if m: route = f"R-{m.group(1)}"
    elif carrier == "ecoscooting":
        m = re.search(r"\b(ALIC\s*\d{2}[A-Z])\b", up)
        if m: zone = re.sub(r"\s+", "", m.group(1))
        m = re.search(r"\b(MAD\s*[-_]\s*ALC\s*1\s*[-_]\s*ALIC\s*\d{2}[A-Z]\s*\d{2,4}\s*[-_]\s*\d{2}\s*[-_]\s*\d{2})\b", up)
        if m: route = re.sub(r"\s+", "", m.group(1)).replace("_", "-")
        elif zone:
            route = zone
    elif carrier == "tipsa":
        m = re.search(r"ALICANTE\s+CENTRO\s*(\d{1,3})", up)
        if m:
            zone = f"ALICANTE CENTRO {m.group(1)}"
            route = m.group(1)
    return zone, route


def _imile_tracking(text, raw_code=""):
    up = _ascii(text or "").upper()
    # Bottom iMile shipping barcode in the supplied labels is a 13-digit shipment code (608...).
    nums = re.findall(r"(?<!\d)(\d{13})(?!\d)", up)
    preferred = [x for x in nums if x.startswith(("608", "609"))]
    if preferred: return preferred[-1]
    if nums: return nums[-1]
    raw = re.sub(r"\D", "", raw_code or "")
    if len(raw) == 13: return raw
    return ""


def _eco_tracking(text, raw_code=""):
    up = _ascii(text or "").upper()
    lp = re.findall(r"\bLP[A-Z0-9]{12,28}\b", up)
    if lp: return max(lp, key=len)
    raw = _compact_upper(raw_code)
    if re.fullmatch(r"LP[A-Z0-9]{12,28}", raw): return raw
    ap = re.findall(r"\bAP\d{10,22}\b", up)
    if ap: return max(ap, key=len)
    # Top linear barcode number fallback; exclude CP-prefix-only fragments when too short.
    nums = re.findall(r"(?<!\d)(\d{16,22})(?!\d)", up)
    if nums: return max(nums, key=len)
    if len(raw) >= 10: return raw
    return ""


def _tipsa_tracking(text, raw_code=""):
    up = _ascii(text or "").upper()
    # In supplied depot labels the top logistics barcode often contains a long unique central segment.
    compound = re.findall(r"\b\d{5,7}\s*[-–]\s*\d{5,7}\s*[-–]\s*(\d{9,13})\s*[-–]\s*\d{2,4}\s*[/|-]\s*\d{2,4}\b", up)
    if compound: return max(compound, key=len)
    # Reference is a safer fallback than postal/time/service codes.
    ref = re.search(r"\bREF\s*[:.]?\s*([A-Z0-9-]{7,20})", up)
    if ref: return ref.group(1).replace(" ", "")
    nums = [x for x in re.findall(r"(?<!\d)(\d{9,13})(?!\d)", up) if not x.startswith(("03012", "03013"))]
    if nums: return max(nums, key=len)
    raw = _compact_upper(raw_code)
    return raw if len(raw) >= 8 else ""


def _generic_tracking(text, raw_code=""):
    raw = _compact_upper(raw_code)
    if len(raw) >= 8: return raw
    candidates = re.findall(r"\b[A-Z]{1,4}\d[A-Z0-9]{8,26}\b|\b\d{11,20}\b", _ascii(text or "").upper())
    return max(candidates, key=len) if candidates else ""


def _address_line_score(line, carrier):
    raw = _clean(line)
    low = _ascii(raw).lower()
    if not raw or len(raw) > 95: return -99
    if any(k in low for k in ("sender", "ship date", "claim weight", "create date", "delivery", "alicante centro", "reembolso", "bultos", "normal", "qty", "pcs")): return -8
    if _looks_code(raw): return -6
    score = 0
    if any(w in low for w in STREET_WORDS): score += 6
    if re.search(r"\d", raw): score += 2
    if re.search(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", raw): score += 1
    if any(k in low for k in ("piso", "puerta", "portal", "planta", "bajo")): score += 2
    if _contains_city(raw): score -= 3
    return score


def _address_imile(text):
    ls = _lines(text)
    # First choice: explicit street line.
    scored = [(i, _address_line_score(line, "imile"), line) for i, line in enumerate(ls)]
    strong = [x for x in scored if x[1] >= 6]
    if strong:
        i, _, line = max(strong, key=lambda x: x[1])
        return line, i
    # iMile can omit the street type, e.g. "Diana 66 2º 3". Look immediately before city block.
    city_idx = [i for i,l in enumerate(ls) if _contains_city(l)]
    for ci in city_idx:
        candidates = []
        for i in range(max(0, ci-4), ci):
            sc = _address_line_score(ls[i], "imile")
            if sc >= 3: candidates.append((i, sc, ls[i]))
        if candidates:
            i, sc, line = max(candidates, key=lambda x: (x[1], x[0]))
            return line, i
    return "", -1


def _address_eco(text):
    ls = _lines(text)
    scored = [(i, _address_line_score(line, "ecoscooting"), line) for i,line in enumerate(ls)]
    strong = [x for x in scored if x[1] >= 6]
    if strong:
        i, _, line = max(strong, key=lambda x: x[1])
        # Join a short continuation line such as "puerta B1" if OCR split it.
        if i+1 < len(ls):
            nxt = ls[i+1]
            nl = _ascii(nxt).lower()
            if len(nxt) < 45 and any(k in nl for k in ("puerta", "piso", "portal", "planta")):
                line = f"{line}, {nxt}"
        return line, i
    return "", -1


def _address_tipsa(text):
    ls = _lines(text)
    # Depot template commonly prefixes destination address with CAL:/CALLE:/DIR:.
    for i,line in enumerate(ls):
        m = re.search(r"\b(?:CAL|CALLE|DIR|DIRECCION|DIRECCIÓN)\s*[:.]?\s*(.+)", line, re.I)
        if m and len(_clean(m.group(1))) >= 4:
            return _clean(m.group(1)), i
    # Fallback to street-like lines.
    scored = [(i, _address_line_score(line, "tipsa"), line) for i,line in enumerate(ls)]
    strong = [x for x in scored if x[1] >= 6]
    if strong:
        i,_,line=max(strong,key=lambda x:x[1]); return line,i
    return "", -1


def _recipient_from_address(text, address_idx, carrier):
    ls = _lines(text)
    if carrier == "tipsa":
        for line in ls:
            m = re.search(r"\b(?:DES|DEST|DESTINATARIO)\s*[:.]?\s*(.+)", line, re.I)
            if m:
                val = _clean(m.group(1))
                if 2 <= len(val) <= 70: return val
    if address_idx > 0:
        # Search up to two lines above the address. Avoid sender/header/code rows.
        for i in range(address_idx-1, max(-1,address_idx-3), -1):
            line = ls[i]
            low = _ascii(line).lower()
            if any(k in low for k in ("sender", "shein", "delivery", "alacant", "alicante", "spain", "esp", "to")): continue
            if _looks_code(line): continue
            words = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ*]+", line)
            if 1 <= len(words) <= 8 and not re.search(r"\d{4,}", line):
                return line
    return ""


def _full_address(address, postal, city, carrier):
    if not address: return ""
    out = _clean(address)
    # Avoid appending CP/city twice when OCR already included them.
    flat = _ascii(out).lower()
    if postal and postal not in out: out += f", {postal}"
    if city and _ascii(city).lower() not in flat:
        out += f", {city}"
    if "espana" not in _ascii(out).lower() and "spain" not in _ascii(out).lower():
        out += ", España"
    return out


def parse_label_text(text: str, raw_code: str = "") -> Dict:
    carrier, carrier_conf, carrier_reason = detect_carrier(text, raw_code)
    postal = _pick_postal(text, carrier)
    city = _pick_city(text, carrier)
    zone, route = _route_fields(text, carrier)

    if carrier == "imile":
        tracking = _imile_tracking(text, raw_code)
        address, address_idx = _address_imile(text)
        profile = "imile_v1"
    elif carrier == "ecoscooting":
        tracking = _eco_tracking(text, raw_code)
        address, address_idx = _address_eco(text)
        profile = "ecoscooting_v1"
    elif carrier == "tipsa":
        tracking = _tipsa_tracking(text, raw_code)
        address, address_idx = _address_tipsa(text)
        profile = "tipsa_agencia_v1"
    else:
        tracking = _generic_tracking(text, raw_code)
        # Generic fallback only; do not over-infer.
        ls = _lines(text)
        candidates=[(i,_address_line_score(l,"unknown"),l) for i,l in enumerate(ls)]
        candidates=[x for x in candidates if x[1]>=6]
        if candidates:
            address_idx,_,address=max(candidates,key=lambda x:x[1])
        else:
            address,address_idx="",-1
        profile = "generic_v1"

    recipient = _recipient_from_address(text, address_idx, carrier)
    phone = _pick_phone(text)
    weight = _pick_weight(text, carrier)
    qty = _pick_qty(text, carrier)
    full_address = _full_address(address, postal, city, carrier)

    detected = {
        "carrier": carrier != "unknown",
        "tracking": bool(tracking),
        "address": bool(address),
        "postal_code": bool(postal),
        "city": bool(city),
        "recipient": bool(recipient),
        "zone": bool(zone),
        "route": bool(route),
        "weight": weight is not None,
    }
    required = ("carrier", "tracking", "address")
    missing_required = [k for k in required if not detected[k]]

    # READY is an intake/classification state. Geocoding is deliberately separate in V0.3.1.3.
    intake_status = "ready" if not missing_required else "review"
    score = 0.0
    score += .25 if detected["carrier"] else 0
    score += .25 if detected["tracking"] else 0
    score += .28 if detected["address"] else 0
    score += .07 if detected["postal_code"] else 0
    score += .04 if detected["city"] else 0
    score += .03 if detected["recipient"] else 0
    score += .04 if detected["zone"] else 0
    score += .02 if detected["route"] else 0
    score += .02 if detected["weight"] else 0
    score = min(.99, score)

    return {
        "carrier": carrier,
        "carrier_reason": carrier_reason,
        "carrier_confidence": round(carrier_conf, 2),
        "profile": profile,
        "tracking_code": tracking,
        "barcode": raw_code or tracking,
        "recipient_name": recipient,
        "phone": phone,
        "address": full_address,
        "postal_code": postal,
        "city": city,
        "route_zone": zone,
        "route_code": route,
        "weight_kg": weight,
        "quantity": qty,
        "intake_confidence": round(score, 2),
        "intake_status": intake_status,
        "missing_required": missing_required,
        "detected_fields": detected,
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
