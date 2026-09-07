import base64
import io
import os
import re
import unicodedata
from typing import Dict, Tuple, Optional, List

import requests
from PIL import Image, ImageOps, ImageFilter, ImageEnhance

# RouteOps V0.3.1.4 — Intelligent OCR Pipeline
# Goals:
# - Use Google Vision DOCUMENT_TEXT_DETECTION instead of generic TEXT_DETECTION.
# - Preprocess label crops for small/low-contrast thermal text.
# - Run an automatic second OCR pass only when important fields are missing.
# - Separate decoded barcode/QR values from carrier-specific tracking selection.
# - Never invent a recipient/address/tracking value.

STREET_WORDS = (
    "calle", "carrer", "avenida", "av.", "av ", "paseo", "passatge", "pasaje",
    "plaza", "plaça", "carretera", "ctra", "camino", "ronda", "travesia",
    "travesía", "urbanizacion", "urbanización", "via", "camí", "cami",
    "rua", "rúa", "bulevar", "boulevard", "glorieta", "pje", "psje",
)

HEADER_WORDS = (
    "sender", "ship date", "claim weight", "create date", "delivery", "urban delivery",
    "alicante centro", "reembolso", "bultos", "normal", "qty", "pcs", "bat & category",
    "country", "spain", "esp", "fecha", "cargo a", "p. pedidos", "portes", "total",
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


def _normalize_codes(raw_code="", raw_codes=None):
    values = []
    if raw_codes:
        for x in raw_codes:
            x = _clean(str(x or ""))
            if x and x not in values:
                values.append(x)
    raw_code = _clean(raw_code)
    if raw_code and raw_code not in values:
        values.insert(0, raw_code)
    return values


def _looks_code(line):
    s = _clean(line)
    if not s:
        return True
    up = _ascii(s).upper()
    # Single normal words are not automatically codes: important for names such as "Pablo".
    if re.fullmatch(r"[A-Z]{1,4}\d[A-Z0-9_./-]{4,39}", up):
        return True
    if re.fullmatch(r"\d{5,30}", re.sub(r"[\s-]", "", s)):
        return True
    if len(re.sub(r"\D", "", s)) >= max(9, int(len(s) * .72)):
        return True
    return False


def _contains_city(line):
    s = _ascii(line).lower()
    return any(x in s for x in ("alicante", "alacant", "denia", "denia,"))


def _person_like(line):
    raw = _clean(line)
    low = _ascii(raw).lower()
    if not raw or len(raw) < 2 or len(raw) > 70:
        return False
    if any(k in low for k in HEADER_WORDS):
        return False
    if _looks_code(raw) or _contains_city(raw):
        return False
    if any(w in low for w in STREET_WORDS):
        return False
    if re.search(r"\b\d{4,}\b", raw):
        return False
    words = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", raw)
    return 1 <= len(words) <= 8


def detect_carrier(text: str, raw_code: str = "", raw_codes=None) -> Tuple[str, float, str]:
    t = _flat(text)
    up = _ascii(text or "").upper()
    compact = _compact_upper(text)
    codes = [_compact_upper(x) for x in _normalize_codes(raw_code, raw_codes)]

    imile_signals = 0
    if re.search(r"\bi\s*m[i1l]\s*[l1i]e\b", t, re.I) or "IMILEDELIVERY" in compact:
        imile_signals += 3
    if re.search(r"\bSHN\b", up):
        imile_signals += 2
    if re.search(r"\bAL\s*C\s*7\b", up):
        imile_signals += 2
    if re.search(r"\bR\s*[-–]?\s*3\b", up):
        imile_signals += 1
    if "BATCATEGORY" in compact:
        imile_signals += 1
    if any(re.fullmatch(r"60[89]\d{10}", re.sub(r"\D", "", c)) for c in codes):
        imile_signals += 1
    if imile_signals >= 4:
        return "imile", min(.99, .67 + imile_signals * .045), "Perfil iMile/SHN"

    eco_signals = 0
    if re.search(r"eco\s*scoot", t) or "ECOSCOOTING" in compact:
        eco_signals += 3
    if re.search(r"\bMAD\s*[-_]\s*ALC\s*1\b", up):
        eco_signals += 2
    if re.search(r"\bLP[A-Z0-9]{12,28}\b", up):
        eco_signals += 2
    if re.search(r"\bALIC\s*\d{2}[A-Z]\b", up):
        eco_signals += 1
    if "CLAIMWEIGHT" in compact:
        eco_signals += 1
    if any(c.startswith("LP") or c.startswith("AP00") for c in codes):
        eco_signals += 1
    if eco_signals >= 4:
        return "ecoscooting", min(.99, .67 + eco_signals * .04), "Perfil Ecoscooting"

    tipsa_signals = 0
    if "TIPSA" in compact:
        tipsa_signals += 3
    if re.search(r"ALICANTE\s+CENTRO\s*\d{1,3}", up):
        tipsa_signals += 3
    for marker in ("REEMBOLSO", "BULTOS", "PPEDIDOS", "CARGOA", "RTE", "DES", "PORTES"):
        if marker in compact:
            tipsa_signals += 1
    if re.search(r"\b0?3\d{3}\s*[/|]\s*\d{1,2}\s*HORAS\b", up):
        tipsa_signals += 1
    if tipsa_signals >= 5:
        return "tipsa", min(.98, .64 + tipsa_signals * .035), "Perfil TIPSA/agencia Alicante Centro"

    return "unknown", .25, "Operadora no identificada"


def _pick_postal(text, carrier="unknown"):
    hits = re.findall(r"(?<!\d)(0\d{4})(?!\d)", text or "")
    if not hits:
        return ""
    if carrier == "imile" and "03700" in hits:
        return "03700"
    if carrier == "ecoscooting" and "03013" in hits:
        return "03013"
    # Prefer values that occur on their own line.
    lines = _lines(text)
    for h in hits:
        if any(re.fullmatch(rf"\D*{re.escape(h)}\D*", ln) for ln in lines):
            return h
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
            try:
                return float(m.group(1).replace(",", "."))
            except Exception:
                pass
    return None


def _pick_qty(text, carrier="unknown"):
    pats = []
    if carrier == "tipsa":
        pats.extend([r"\bBULTOS\s*[:=]?\s*(\d+)\b", r"\bBULTO[S]?\s+(\d+)\b"])
    pats.extend([r"\bQty\s*[:=]?\s*(\d+)\b", r"\bCantidad\s*[:=]?\s*(\d+)\b"])
    for p in pats:
        m = re.search(p, text or "", re.I)
        if m:
            try:
                return max(1, int(m.group(1)))
            except Exception:
                pass
    return 1


def _pick_phone(text):
    # Do not construct a phone number from masked Ecoscooting text.
    for line in _lines(text):
        if "*" in line:
            continue
        compact = re.sub(r"[\s-]", "", line)
        m = re.search(r"(?<!\d)([6789]\d{8})(?!\d)", compact)
        if m:
            return m.group(1)
    return ""


def _route_fields(text, carrier):
    up = _ascii(text or "").upper()
    zone = route = ""
    if carrier == "imile":
        m = re.search(r"\bAL\s*C\s*([0-9A-Z]{1,3})\b", up)
        if m:
            zone = "ALC" + re.sub(r"\s+", "", m.group(1))
        m = re.search(r"\bR\s*[-–]?\s*(\d{1,3})\b", up)
        if m:
            route = f"R-{m.group(1)}"
    elif carrier == "ecoscooting":
        m = re.search(r"\b(ALIC\s*\d{2}[A-Z])\b", up)
        if m:
            zone = re.sub(r"\s+", "", m.group(1))
        m = re.search(r"\b(MAD\s*[-_]\s*ALC\s*1\s*[-_]\s*ALIC\s*\d{2}[A-Z]\s*\d{2,4}\s*[-_]\s*\d{2}\s*[-_]\s*\d{2})\b", up)
        if m:
            route = re.sub(r"\s+", "", m.group(1)).replace("_", "-")
        elif zone:
            route = zone
    elif carrier == "tipsa":
        m = re.search(r"ALICANTE\s+CENTRO\s*(\d{1,3})", up)
        if m:
            zone = f"ALICANTE CENTRO {m.group(1)}"
            route = m.group(1)
    return zone, route


def _candidate_pool(text, raw_code="", raw_codes=None):
    codes = _normalize_codes(raw_code, raw_codes)
    up = _ascii(text or "").upper()
    ocr_candidates = []
    ocr_candidates += re.findall(r"\bLP[A-Z0-9]{10,30}\b", up)
    ocr_candidates += re.findall(r"\bAP\d{9,24}\b", up)
    ocr_candidates += re.findall(r"(?<!\d)\d{11,22}(?!\d)", re.sub(r"[ ]", "", up))
    out = []
    for value, source in [(x, "scan") for x in codes] + [(x, "ocr") for x in ocr_candidates]:
        v = _clean(value)
        if v and all(v != y[0] for y in out):
            out.append((v, source))
    return out


def _imile_tracking(text, raw_code="", raw_codes=None):
    pool = _candidate_pool(text, raw_code, raw_codes)
    normalized = [(re.sub(r"\D", "", v), src, v) for v, src in pool]
    for digits, src, original in normalized:
        if re.fullmatch(r"60[89]\d{10}", digits):
            return digits, f"{src}_imile_13"
    # OCR text under iMile main barcode can be slightly separated by spaces.
    for digits in re.findall(r"(?<!\d)(60[89](?:\s*\d){10})(?!\d)", _ascii(text or "")):
        value = re.sub(r"\D", "", digits)
        if len(value) == 13:
            return value, "ocr_imile_13"
    for digits, src, original in normalized:
        if len(digits) == 13:
            return digits, f"{src}_13_digit_fallback"
    return "", ""


def _eco_tracking(text, raw_code="", raw_codes=None):
    pool = _candidate_pool(text, raw_code, raw_codes)
    for value, src in pool:
        compact = _compact_upper(value)
        if re.fullmatch(r"LP[A-Z0-9]{12,28}", compact):
            return compact, f"{src}_lp"
    up = _ascii(text or "").upper()
    lp = re.findall(r"\bLP[A-Z0-9]{12,28}\b", up)
    if lp:
        return max(lp, key=len), "ocr_lp"
    # AP is internal/secondary on supplied labels, so it is only a fallback.
    for value, src in pool:
        compact = _compact_upper(value)
        if re.fullmatch(r"AP\d{10,24}", compact):
            return compact, f"{src}_ap_fallback"
    nums = [re.sub(r"\D", "", v) for v, _ in pool]
    nums = [x for x in nums if 16 <= len(x) <= 22 and not x.startswith("03013")]
    if nums:
        return max(nums, key=len), "numeric_fallback"
    return "", ""


def _tipsa_tracking(text, raw_code="", raw_codes=None):
    up = _ascii(text or "").upper()
    # Compound top barcode format observed on the depot labels.
    compound = re.findall(r"\b\d{5,7}\s*[-–]\s*\d{5,7}\s*[-–]\s*(\d{9,13})\s*[-–]\s*\d{2,4}\s*[/|-]\s*\d{2,4}\b", up)
    if compound:
        return max(compound, key=len), "ocr_tipsa_compound"
    ref = re.search(r"\bREF\s*[:.]?\s*([A-Z0-9-]{7,40})", up)
    if ref:
        return ref.group(1).replace(" ", ""), "ocr_ref"
    pool = _candidate_pool(text, raw_code, raw_codes)
    # Avoid service/postal/time codes. Prefer long scanned linear codes.
    scored = []
    for value, src in pool:
        compact = _compact_upper(value)
        digits = re.sub(r"\D", "", compact)
        if len(digits) < 9 or digits.startswith(("03012", "03013", "03700")):
            continue
        score = len(digits) + (3 if src == "scan" else 0)
        scored.append((score, digits or compact, src))
    if scored:
        _, value, src = max(scored)
        return value, f"{src}_tipsa_fallback"
    return "", ""


def _generic_tracking(text, raw_code="", raw_codes=None):
    pool = _candidate_pool(text, raw_code, raw_codes)
    scored = []
    for value, src in pool:
        compact = _compact_upper(value)
        if len(compact) < 8:
            continue
        score = min(len(compact), 24)
        if compact.startswith("LP"):
            score += 12
        elif re.search(r"[A-Z]", compact) and re.search(r"\d", compact):
            score += 5
        if src == "ocr":
            score += 1
        scored.append((score, compact, src))
    if not scored:
        return "", ""
    _, value, src = max(scored)
    return value, f"{src}_generic"


def _address_line_score(line, carrier):
    raw = _clean(line)
    low = _ascii(raw).lower()
    if not raw or len(raw) > 110:
        return -99
    if any(k in low for k in HEADER_WORDS):
        return -8
    if _looks_code(raw):
        return -6
    score = 0
    if any(w in low for w in STREET_WORDS):
        score += 7
    if re.search(r"\d", raw):
        score += 3
    if re.search(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", raw):
        score += 1
    if any(k in low for k in ("piso", "puerta", "portal", "planta", "bajo", "º", "°")):
        score += 2
    if re.search(r"\b(?:n|num|numero|número)\.?\s*\d+", low):
        score += 2
    if _contains_city(raw):
        score -= 3
    return score


def _append_continuation(ls, i, line):
    if i + 1 >= len(ls):
        return line
    nxt = _clean(ls[i + 1])
    nl = _ascii(nxt).lower()
    if not nxt or _contains_city(nxt) or re.fullmatch(r"0\d{4}", nxt):
        return line
    if len(nxt) <= 28 and (
        any(k in nl for k in ("puerta", "piso", "portal", "planta", "bajo"))
        or re.fullmatch(r"[A-Z]?\d?[A-Z]?", nxt, re.I)
    ):
        return f"{line}, {nxt}"
    return line


def _address_imile(text):
    ls = _lines(text)
    # Prefer the recipient block around the destination city/postal row, not sender Madrid lines.
    anchors = [i for i, line in enumerate(ls) if _contains_city(line) or re.fullmatch(r"0\d{4}", line)]
    for anchor in anchors:
        candidates = []
        for i in range(max(0, anchor - 6), anchor):
            sc = _address_line_score(ls[i], "imile")
            if sc >= 4:
                # Favor the closest plausible line before destination city/CP.
                candidates.append((sc + i * .02, i, ls[i]))
        if candidates:
            _, i, line = max(candidates)
            return _append_continuation(ls, i, line), i
    strong = [(i, _address_line_score(line, "imile"), line) for i, line in enumerate(ls)]
    strong = [x for x in strong if x[1] >= 7]
    if strong:
        i, _, line = max(strong, key=lambda x: x[1])
        return _append_continuation(ls, i, line), i
    return "", -1


def _address_eco(text):
    ls = _lines(text)
    # Address is generally after masked recipient/phone and before lower AP/weight section.
    star_indices = [i for i, line in enumerate(ls) if "*" in line]
    for anchor in star_indices:
        candidates = []
        for i in range(anchor + 1, min(len(ls), anchor + 6)):
            sc = _address_line_score(ls[i], "ecoscooting")
            if sc >= 5:
                candidates.append((sc, i, ls[i]))
        if candidates:
            _, i, line = max(candidates)
            return _append_continuation(ls, i, line), i
    candidates = [(i, _address_line_score(line, "ecoscooting"), line) for i, line in enumerate(ls)]
    candidates = [x for x in candidates if x[1] >= 7]
    if candidates:
        i, _, line = max(candidates, key=lambda x: x[1])
        return _append_continuation(ls, i, line), i
    return "", -1


def _address_tipsa(text):
    ls = _lines(text)
    for i, line in enumerate(ls):
        # CAL often carries the delivery street on depot labels.
        m = re.search(r"\b(?:CAL|CALLE|DIR|DIRECCION|DIRECCIÓN)\s*[:.]?\s*(.+)", line, re.I)
        if m and len(_clean(m.group(1))) >= 4:
            return _clean(m.group(1)), i
    # Sometimes OCR splits "CAL:" and the value onto the next line.
    for i, line in enumerate(ls[:-1]):
        if re.fullmatch(r"(?:CAL|CALLE|DIR|DIRECCION|DIRECCIÓN)\s*[:.]?", line, re.I):
            val = _clean(ls[i + 1])
            if len(val) >= 4:
                return val, i + 1
    candidates = [(i, _address_line_score(line, "tipsa"), line) for i, line in enumerate(ls)]
    candidates = [x for x in candidates if x[1] >= 7]
    if candidates:
        i, _, line = max(candidates, key=lambda x: x[1])
        return line, i
    return "", -1


def _recipient_imile(text, address_idx):
    ls = _lines(text)
    if address_idx > 0:
        for i in range(address_idx - 1, max(-1, address_idx - 4), -1):
            if _person_like(ls[i]):
                return ls[i]
    # Explicit TO block fallback: first person-like line after TO.
    for i, line in enumerate(ls):
        if re.fullmatch(r"TO[:.]?", _ascii(line).upper()):
            for j in range(i + 1, min(len(ls), i + 5)):
                if _person_like(ls[j]):
                    return ls[j]
    return ""


def _recipient_eco(text, address_idx):
    ls = _lines(text)
    # Ecoscooting masks surnames/phone. Preserve only the visible name part; do not invent hidden text.
    for line in ls:
        if "*" in line:
            prefix = _clean(line.split("*", 1)[0])
            if _person_like(prefix):
                return prefix
    if address_idx > 0:
        for i in range(address_idx - 1, max(-1, address_idx - 5), -1):
            line = ls[i]
            if "*" in line:
                continue
            if _person_like(line):
                return line
    return ""


def _recipient_tipsa(text, address_idx):
    ls = _lines(text)
    for i, line in enumerate(ls):
        m = re.search(r"\b(?:DES|DEST|DESTINATARIO)\s*[:.]?\s*(.+)", line, re.I)
        if m:
            val = _clean(m.group(1))
            if 2 <= len(val) <= 80 and not _looks_code(val):
                return val
        if re.fullmatch(r"(?:DES|DEST|DESTINATARIO)\s*[:.]?", line, re.I) and i + 1 < len(ls):
            val = _clean(ls[i + 1])
            if 2 <= len(val) <= 80 and not _looks_code(val):
                return val
    return ""


def _recipient_generic(text, address_idx):
    ls = _lines(text)
    if address_idx > 0:
        for i in range(address_idx - 1, max(-1, address_idx - 4), -1):
            if _person_like(ls[i]):
                return ls[i]
    return ""


def _full_address(address, postal, city):
    if not address:
        return ""
    out = _clean(address)
    flat = _ascii(out).lower()
    if postal and postal not in out:
        out += f", {postal}"
    if city and _ascii(city).lower() not in flat:
        out += f", {city}"
    if "espana" not in _ascii(out).lower() and "spain" not in _ascii(out).lower():
        out += ", España"
    return out


def _extraction_score(parsed):
    d = parsed.get("detected_fields") or {}
    return (
        (6 if d.get("carrier") else 0)
        + (7 if d.get("tracking") else 0)
        + (10 if d.get("address") else 0)
        + (5 if d.get("recipient") else 0)
        + (3 if d.get("postal_code") else 0)
        + (2 if d.get("city") else 0)
        + (2 if d.get("zone") else 0)
        + (1 if d.get("route") else 0)
        + (1 if d.get("weight") else 0)
        + float(parsed.get("intake_confidence") or 0)
    )


def parse_label_text(text: str, raw_code: str = "", raw_codes=None, forced_carrier: str = "") -> Dict:
    codes = _normalize_codes(raw_code, raw_codes)
    if forced_carrier in {"imile", "ecoscooting", "tipsa"}:
        carrier = forced_carrier
        carrier_conf = .99
        carrier_reason = "Operadora confirmada por repartidor"
    else:
        carrier, carrier_conf, carrier_reason = detect_carrier(text, raw_code, codes)

    postal = _pick_postal(text, carrier)
    city = _pick_city(text, carrier)
    zone, route = _route_fields(text, carrier)

    if carrier == "imile":
        tracking, tracking_source = _imile_tracking(text, raw_code, codes)
        address, address_idx = _address_imile(text)
        recipient = _recipient_imile(text, address_idx)
        profile = "imile_v2"
    elif carrier == "ecoscooting":
        tracking, tracking_source = _eco_tracking(text, raw_code, codes)
        address, address_idx = _address_eco(text)
        recipient = _recipient_eco(text, address_idx)
        profile = "ecoscooting_v2"
    elif carrier == "tipsa":
        tracking, tracking_source = _tipsa_tracking(text, raw_code, codes)
        address, address_idx = _address_tipsa(text)
        recipient = _recipient_tipsa(text, address_idx)
        profile = "tipsa_agencia_v2"
    else:
        tracking, tracking_source = _generic_tracking(text, raw_code, codes)
        ls = _lines(text)
        candidates = [(i, _address_line_score(line, "unknown"), line) for i, line in enumerate(ls)]
        candidates = [x for x in candidates if x[1] >= 7]
        if candidates:
            address_idx, _, address = max(candidates, key=lambda x: x[1])
        else:
            address, address_idx = "", -1
        recipient = _recipient_generic(text, address_idx)
        profile = "generic_v2"

    phone = _pick_phone(text)
    weight = _pick_weight(text, carrier)
    qty = _pick_qty(text, carrier)
    full_address = _full_address(address, postal, city)

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
    intake_status = "ready" if not missing_required else "review"

    score = 0.0
    score += .22 if detected["carrier"] else 0
    score += .23 if detected["tracking"] else 0
    score += .27 if detected["address"] else 0
    score += .09 if detected["recipient"] else 0
    score += .06 if detected["postal_code"] else 0
    score += .04 if detected["city"] else 0
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
        "tracking_source": tracking_source,
        # Barcode is deliberately separate from tracking.
        "barcode": codes[0] if codes else "",
        "barcode_candidates": codes,
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


def _vision_url_and_headers():
    project = (os.environ.get("GOOGLE_CLOUD_PROJECT") or "").strip()
    key = (os.environ.get("GOOGLE_VISION_API_KEY") or "").strip()
    headers = {"Content-Type": "application/json"}
    if key:
        return f"https://vision.googleapis.com/v1/images:annotate?key={key}", headers, None
    cred_path = (os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or "").strip()
    if not (project and cred_path):
        return None, headers, "OCR no configurado"
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request as GoogleAuthRequest
        creds = service_account.Credentials.from_service_account_file(
            cred_path, scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        creds.refresh(GoogleAuthRequest())
        headers["Authorization"] = f"Bearer {creds.token}"
        return f"https://eu-vision.googleapis.com/v1/projects/{project}/locations/eu/images:annotate", headers, None
    except Exception as exc:
        return None, headers, f"Credenciales Vision: {exc}"


def _image_for_ocr(image_bytes: bytes, mode="color") -> bytes:
    with Image.open(io.BytesIO(image_bytes)) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        # Trim a tiny outer margin left by the perspective crop; no aggressive crop.
        w, h = im.size
        if w > 300 and h > 300:
            mx, my = max(2, int(w * .006)), max(2, int(h * .006))
            im = im.crop((mx, my, w - mx, h - my))
        w, h = im.size
        long_side = max(w, h)
        target = int(os.environ.get("OCR_TARGET_LONG_SIDE", "2200"))
        target = max(1400, min(target, 2800))
        if long_side != target:
            scale = target / max(1, long_side)
            # Upscale smaller thermal labels, downscale huge camera frames.
            if scale > 1.05 or scale < .88:
                im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)
        if mode == "mono":
            gray = ImageOps.grayscale(im)
            gray = ImageOps.autocontrast(gray, cutoff=.4)
            gray = ImageEnhance.Contrast(gray).enhance(1.45)
            gray = gray.filter(ImageFilter.UnsharpMask(radius=1.2, percent=145, threshold=2))
            im = gray.convert("RGB")
        else:
            im = ImageOps.autocontrast(im, cutoff=.25)
            im = ImageEnhance.Contrast(im).enhance(1.12)
            im = ImageEnhance.Sharpness(im).enhance(1.35)
            im = im.filter(ImageFilter.UnsharpMask(radius=1.0, percent=105, threshold=3))
        out = io.BytesIO()
        im.save(out, format="JPEG", quality=93, optimize=True)
        return out.getvalue()


def google_vision_document(image_bytes: bytes) -> Tuple[Optional[Dict], Optional[str]]:
    if not image_bytes:
        return None, "Imagen vacía"
    url, headers, err = _vision_url_and_headers()
    if err:
        return None, err
    payload = {
        "requests": [{
            "image": {"content": base64.b64encode(image_bytes).decode("ascii")},
            "features": [{"type": "DOCUMENT_TEXT_DETECTION", "maxResults": 1}],
            "imageContext": {"languageHints": ["es", "en"]},
        }]
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        if not r.ok:
            return None, f"Vision HTTP {r.status_code}: {r.text[:240]}"
        data = r.json()
        resp = (data.get("responses") or [{}])[0]
        if resp.get("error"):
            return None, str(resp["error"])
        full = resp.get("fullTextAnnotation") or {}
        text = full.get("text") or ""
        if not text:
            ann = resp.get("textAnnotations") or []
            if ann:
                text = ann[0].get("description") or ""
        if not text:
            return None, "No se detectó texto"

        confidences = []
        word_count = 0
        for page in full.get("pages") or []:
            for block in page.get("blocks") or []:
                if isinstance(block.get("confidence"), (int, float)):
                    confidences.append(float(block["confidence"]))
                for paragraph in block.get("paragraphs") or []:
                    if isinstance(paragraph.get("confidence"), (int, float)):
                        confidences.append(float(paragraph["confidence"]))
                    for word in paragraph.get("words") or []:
                        word_count += 1
                        if isinstance(word.get("confidence"), (int, float)):
                            confidences.append(float(word["confidence"]))
        mean_conf = sum(confidences) / len(confidences) if confidences else None
        return {
            "text": text,
            "confidence": round(mean_conf, 3) if mean_conf is not None else None,
            "word_count": word_count,
        }, None
    except Exception as exc:
        return None, f"Vision error: {exc}"


def extract_label_data(image_bytes: bytes, raw_code="", raw_codes=None, forced_carrier="") -> Dict:
    """High-accuracy OCR + carrier parser.

    Pass 1: enhanced color DOCUMENT_TEXT_DETECTION.
    Pass 2: high-contrast grayscale only if recipient/address/tracking/carrier extraction is weak.
    """
    codes = _normalize_codes(raw_code, raw_codes)
    pass1_bytes = _image_for_ocr(image_bytes, "color")
    ocr1, err1 = google_vision_document(pass1_bytes)
    if not ocr1:
        raise RuntimeError(err1 or "OCR sin resultado")

    parsed1 = parse_label_text(ocr1["text"], raw_code, codes, forced_carrier)
    best = parsed1
    best_text = ocr1["text"]
    ocr_conf = ocr1.get("confidence")
    passes = 1
    errors = [x for x in [err1] if x]

    d1 = parsed1.get("detected_fields") or {}
    need_second = (
        not d1.get("carrier")
        or not d1.get("tracking")
        or not d1.get("address")
        or not d1.get("recipient")
        or float(parsed1.get("intake_confidence") or 0) < .75
    )
    multipass = os.environ.get("OCR_MULTI_PASS", "1").strip().lower() not in {"0", "false", "no"}
    if need_second and multipass:
        try:
            pass2_bytes = _image_for_ocr(image_bytes, "mono")
            ocr2, err2 = google_vision_document(pass2_bytes)
            if err2:
                errors.append(err2)
            if ocr2:
                passes = 2
                candidates = [
                    (parse_label_text(ocr2["text"], raw_code, codes, forced_carrier), ocr2["text"], ocr2.get("confidence")),
                    (parse_label_text(ocr1["text"] + "\n" + ocr2["text"], raw_code, codes, forced_carrier), ocr1["text"] + "\n" + ocr2["text"], max(x for x in [ocr1.get("confidence"), ocr2.get("confidence")] if x is not None) if any(x is not None for x in [ocr1.get("confidence"), ocr2.get("confidence")]) else None),
                ]
                for candidate, text, conf in candidates:
                    if _extraction_score(candidate) > _extraction_score(best):
                        best, best_text, ocr_conf = candidate, text, conf
        except Exception as exc:
            errors.append(str(exc))

    best["ocr_passes"] = passes
    best["ocr_confidence"] = ocr_conf
    best["ocr_errors"] = errors
    # Returned for transient diagnostics only; caller decides whether to persist (RouteOps does not).
    best["ocr_text"] = best_text
    return best


def google_vision_text(image_bytes: bytes) -> Tuple[Optional[str], Optional[str]]:
    """Backward-compatible helper used by older RouteOps code."""
    try:
        prepared = _image_for_ocr(image_bytes, "color")
        result, err = google_vision_document(prepared)
        return (result.get("text") if result else None), err
    except Exception as exc:
        return None, f"Vision error: {exc}"
