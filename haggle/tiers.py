"""Deterministic GPU performance tiers.

"Is an RX 6700 XT equivalent to an RTX 3060?" is answered from this table, not from the LLM's
memory, so verdicts are reproducible. Scores are rough relative 1080p raster performance
(RTX 3060 desktop = 100), compiled from public benchmark aggregates.
"""
import re

GPU_SCORE = {
    "gt 1030": 15, "gtx 1050": 25, "gtx 1050 ti": 32, "gtx 1060": 50, "gtx 1070": 63,
    "gtx 1070 ti": 70, "gtx 1080": 75, "gtx 1080 ti": 95, "gtx 1650": 40, "gtx 1650 super": 50,
    "gtx 1660": 58, "gtx 1660 super": 65, "gtx 1660 ti": 66,
    "rtx 2060": 80, "rtx 2060 super": 92, "rtx 2070": 95, "rtx 2070 super": 105, "rtx 2080": 112,
    "rtx 2080 super": 117, "rtx 2080 ti": 135,
    "rtx 3050": 70, "rtx 3060": 100, "rtx 3060 ti": 122, "rtx 3070": 138, "rtx 3070 ti": 145,
    "rtx 3080": 170, "rtx 3080 ti": 185, "rtx 3090": 192,
    "rtx 4060": 112, "rtx 4060 ti": 135, "rtx 4070": 175, "rtx 4070 super": 200, "rtx 4070 ti": 210,
    "rtx 4080": 255, "rtx 4090": 320, "rtx 5060": 140, "rtx 5060 ti": 160, "rtx 5070": 215,
    "rx 570": 45, "rx 580": 50, "rx 590": 55, "rx 5500 xt": 55, "rx 5600 xt": 80, "rx 5700": 90,
    "rx 5700 xt": 100, "rx 6500 xt": 45, "rx 6600": 98, "rx 6600 xt": 112, "rx 6650 xt": 118,
    "rx 6700": 125, "rx 6700 xt": 135, "rx 6750 xt": 142, "rx 6800": 165, "rx 6800 xt": 185,
    "rx 6900 xt": 195, "rx 7600": 115, "rx 7700 xt": 170, "rx 7800 xt": 200,
    "arc a580": 95, "arc a750": 105, "arc a770": 112, "arc b580": 125,
    "integrated": 10,
}


def normalize_gpu(name):
    """'3060ti' / 'GeForce RTX 3060 Ti 8GB' / 'rx6700xt' -> canonical key, or None."""
    if not name:
        return None
    s = name.lower()
    if any(w in s for w in ("intel uhd", "intel hd", "integrated", "inbyggd", "vega 8", "iris")):
        return "integrated"
    laptop = "laptop" in s or "mobile" in s or "max-q" in s
    s = re.sub(r"(geforce|nvidia|amd|radeon|intel|\d+\s?gb|oc|edition|founders|gaming|laptop|mobile)", " ", s)
    s = s.replace("-", " ")
    s = re.sub(r"(rtx|gtx|rx|gt|arc)\s*(\d)", r"\1 \2", s)
    s = re.sub(r"(\d)\s*(ti|super|xt)\b", r"\1 \2", s)
    s = re.sub(r"\s+", " ", s).strip()
    m = re.search(r"(rtx|gtx|rx|gt|arc)?\s?([ab]?\d{3,4})( ti| super| xt)?( super)?", s)
    if not m:
        return None
    prefix, num, suf, suf2 = m.group(1), m.group(2), m.group(3) or "", m.group(4) or ""
    if not prefix:
        n = int(re.sub(r"\D", "", num) or 0)
        prefix = "rx" if 5000 <= n < 8000 and suf.strip() == "xt" else ("arc" if num[0] in "ab" else ("gtx" if n < 2000 else "rtx"))
    key = f"{prefix} {num}{suf}{suf2}".strip()
    if key not in GPU_SCORE and f"{prefix} {num}" in GPU_SCORE:
        key = f"{prefix} {num}"
    if key not in GPU_SCORE:
        return None
    return key + (" laptop" if laptop else "")


def gpu_score(name):
    key = normalize_gpu(name)
    if key is None:
        return None
    if key.endswith(" laptop"):  # laptop variants run ~25% slower than the desktop card
        return round(GPU_SCORE[key[:-7]] * 0.75)
    return GPU_SCORE[key]
