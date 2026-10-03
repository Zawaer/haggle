"""Steps 1-5 of the hunt: intake -> search -> extract -> match & vet -> rank.

LLMs do language work (turning a request into a schema, reading messy listings). Everything that
decides something (does it pass, is it risky, which is best) is deterministic code over the
extracted facts, so verdicts are explainable and reproducible.
"""
import re
import statistics
import math
import unicodedata

from . import config, marketplace
from .llm import ask_json
from .tiers import gpu_score, normalize_gpu

STOCKHOLM_AREA = [
    "stockholm", "solna", "sundbyberg", "nacka", "huddinge", "täby", "lidingö", "danderyd", "bromma",
    "södermalm", "kungsholmen", "vasastan", "östermalm", "hägersten", "farsta", "skärholmen", "järfälla",
    "sollentuna", "upplands väsby", "haninge", "tyresö", "botkyrka", "kista", "spånga", "vällingby",
    "hammarby", "älvsjö", "enskede", "årsta", "liljeholmen", "sickla", "jakobsberg", "märsta", "värmdö",
    "norrtälje", "södertälje", "akalla", "rinkeby", "midsommarkransen", "gröndal", "aspudden",
]

# ---------------------------------------------------------------- 1. Intake

# Listings asking up to this much over budget are still worth messaging (sellers usually come down 10-20%).
NEGOTIABLE_OVER = 1.25
EXPECTED_AFTER_HAGGLE = 0.9   # typical final price / asking price, used only for ranking

INTAKE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "One-line restatement of what the user wants."},
        "category": {"type": "string", "enum": ["desktop_pc", "laptop", "gpu_only", "console", "other"]},
        "budget_max_sek": {"type": "number", "description": "Hard ceiling. Never pay more."},
        "target_price_sek": {"type": "number", "description": "What a good deal looks like, ~10-15% under budget unless stated."},
        "gpu_min": {"type": "string", "description": "Minimum GPU model, e.g. 'RTX 3060'. Empty if none."},
        "gpu_allow_equivalent": {"type": "boolean"},
        "ram_gb_min": {"type": "number", "description": "0 if not specified."},
        "storage_gb_min": {"type": "number", "description": "0 if not specified. 1 TB = 1000."},
        "storage_ssd_required": {"type": "boolean"},
        "city": {"type": "string"},
        "shipping_ok": {"type": "boolean"},
        "used_ok": {"type": "boolean"},
        "search_queries": {
            "type": "array", "items": {"type": "string"},
            "description": "6-10 short marketplace search queries in Swedish AND English, the way sellers "
                           "actually write titles (e.g. 'speldator rtx 3060', 'gaming pc 3060', 'stationär dator 16gb').",
        },
        "unsupported_requirements": {"type": "array", "items": {"type": "string"},
            "description": "List every hard constraint this schema cannot represent (e.g. CPU model, brand, screen size, warranty). Never silently drop constraints. Empty if all are represented. "
                           "Use cases are NOT unsupported: translate them into specs instead (see the system prompt)."},
        "clarifying_question": {
            "type": "string",
            "description": "Ask ONE question only if something essential is truly ambiguous (e.g. 'good for gaming' "
                           "with no GPU and no budget). Write it in the SAME language as the user's request "
                           "(English request -> English question). Otherwise empty string.",
        },
    },
    "required": ["summary", "category", "budget_max_sek", "target_price_sek", "gpu_min", "gpu_allow_equivalent",
                 "ram_gb_min", "storage_gb_min", "storage_ssd_required", "city", "shipping_ok", "used_ok",
                 "search_queries", "clarifying_question", "unsupported_requirements"],
}


CLARIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "ready": {"type": "boolean", "description": "True if the request already has a budget, the kind of item and "
                                                    "enough detail to search well. Then questions may be empty."},
        "summary": {"type": "string", "description": "One-line restatement of what you understood so far."},
        "questions": {
            "type": "array", "maxItems": 3,
            "description": "0-3 short questions, most important first. Ask ONLY about things that change the search: "
                           "max budget (always ask if missing), kind of item (desktop / laptop / graphics card), what it is "
                           "for or the minimum specs (e.g. which games -> GPU), and pickup city or shipping. Never ask about "
                           "things already stated. Same language as the request.",
            "items": {"type": "object", "properties": {
                "id": {"type": "string", "enum": ["budget", "category", "use", "specs", "location", "other"]},
                "question": {"type": "string"},
                "options": {"type": "array", "maxItems": 4, "items": {"type": "string"},
                            "description": "2-4 short, typical answers the user can tap, e.g. '8 000 kr', 'Stockholm, pickup'."},
            }, "required": ["id", "question", "options"]},
        },
    },
    "required": ["ready", "summary", "questions"],
}


_SV = re.compile(r"[åäö]|\b(jag|vill|ett|och|har|behöver|söker|dator|datorn|köpa|billig|begagnad|helst)\b", re.I)


def language(text):
    """'Swedish' or 'English': decided in code, because the model drifts to Swedish for a Swedish marketplace."""
    return "Swedish" if _SV.search(text or "") else "English"


async def clarify(request, budget):
    """Before a hunt: which questions to ask the user first (web app, or the agent's skill via MCP).
    The hunt itself then never asks: it only searches, vets and negotiates."""
    lang = language(request)
    result = await ask_json(
        f"User request: {request}\nWrite the summary, questions and options in {lang}.", CLARIFY_SCHEMA, budget=budget,
        system="You help a shopper buying second-hand electronics in Sweden (desktop PCs, laptops, graphics cards) "
               "on a marketplace. Decide what you still need to know before searching. Ask as few questions as "
               "possible; a request with a budget, the kind of item and the main specs is ready. Write in the "
               "language the user wrote in.",
    )
    qs = [q for q in result.get("questions") or [] if (q.get("question") or "").strip()][:3]
    for q in qs:
        q["options"] = [o for o in (q.get("options") or []) if str(o).strip()][:4]
    return {"ready": bool(result.get("ready")) and not qs, "summary": result.get("summary", ""), "questions": qs}


def with_answers(request, answers):
    """Fold the user's answers to the clarifying questions into the request text."""
    lines = [f"- {a['question'].strip()} {a['answer'].strip()}" for a in answers or []
             if (a.get("answer") or "").strip()]
    return request.strip() + ("\nAnswers to follow-up questions:\n" + "\n".join(lines) if lines else "")


async def intake(request, budget, answer=None, clarified=False):
    prompt = f"User request: {request}"
    if answer:
        prompt += f"\nAnswer to your clarifying question: {answer}\nDo not ask another question."
    elif clarified:
        prompt += ("\nThe user already answered the follow-up questions. Do NOT ask anything: leave clarifying_question "
                   "empty and use sensible defaults for anything still unstated, EXCEPT the budget: if no budget was given "
                   "anywhere, set budget_max_sek to 0 (never guess a budget).")
    result = await ask_json(
        prompt, INTAKE_SCHEMA, budget=budget,
        system="You turn a shopper's request for a second-hand purchase in Sweden into structured requirements. "
               "Anything you say to the user (summary, clarifying question) must be in the language the user wrote in; "
               "only the search queries mix Swedish and English. "
               "Translate use cases into concrete minimum specs yourself, never into unsupported_requirements: "
               "named games or 'gaming' -> a GPU class and RAM (unreleased or very demanding games such as GTA 6 -> "
               "RTX 3060 or equivalent, 16 GB RAM, SSD; esports/older games -> GTX 1660 class, 16 GB RAM); "
               "video editing/3D -> RTX 3060+, 32 GB RAM; office/school -> no GPU minimum, 8 GB RAM, SSD.",
    )

    if clarified:
        result["clarifying_question"] = ""
    if result.get("clarifying_question", "").strip() and not answer:
        return result
    ceiling = result["budget_max_sek"]
    if not isinstance(ceiling, (int, float)) or not math.isfinite(ceiling) or ceiling <= 0:
        raise ValueError("Please give a maximum budget in SEK (ask the user, then start a new hunt).")
    if result["category"] not in ("desktop_pc", "laptop", "gpu_only"):
        raise ValueError("This version supports desktop PCs, laptops and graphics cards. Please narrow the request.")
    if result.get("unsupported_requirements"):
        raise ValueError("Cannot reliably verify these requirements yet: " + ", ".join(result["unsupported_requirements"]))
    return result


# ---------------------------------------------------------------- 3. Extract

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": ["desktop_pc", "laptop", "gpu_only", "parts", "console", "other"]},
        "gpu": {"type": "string", "description": "GPU model as written, e.g. 'RTX 3060 Ti'. Empty if not stated."},
        "gpu_is_laptop_variant": {"type": "boolean"},
        "cpu": {"type": "string", "description": "Empty if not stated."},
        "ram_gb": {"type": "number", "description": "-1 if not stated."},
        "ssd_gb": {"type": "number", "description": "Total SSD/NVMe capacity in GB, -1 if not stated, 0 if clearly none."},
        "hdd_gb": {"type": "number", "description": "Total HDD capacity in GB, -1 if not stated, 0 if none."},
        "storage_type_unclear_gb": {"type": "number", "description": "Capacity stated without saying SSD or HDD, else 0."},
        "working": {"type": "string", "enum": ["yes", "no", "unknown"]},
        "condition": {"type": "string", "enum": ["new", "used", "unknown"]},
        "evidence": {
            "type": "array", "items": {"type": "string"},
            "description": "Short verbatim quotes from the listing that support the extracted specs.",
        },
        "contradictions": {"type": "string", "description": "Title vs description conflicts, e.g. title says 3060 but text says 3050. Empty if none."},
        "risk_signals": {
            "type": "array", "items": {"type": "string"},
            "description": "Scam/risk signals in the text: prepayment/bank transfer only, seller abroad, shipping only, urgency, "
                           "copy-paste/stock wording, too-good-to-be-true. Empty if none.",
        },
        "language": {"type": "string", "enum": ["sv", "en"]},
        "is_for_sale": {"type": "boolean", "description": "False for wanted ads (KÖPES / WTB), swap-only ads or service offers."},
    },
    "required": ["category", "gpu", "gpu_is_laptop_variant", "cpu", "ram_gb", "ssd_gb", "hdd_gb",
                 "storage_type_unclear_gb", "working", "condition", "evidence", "contradictions", "risk_signals", "language", "is_for_sale"],
}


async def extract(listing, budget):
    text = (f"Source: {listing['source']}\nTitle: {listing['title']}\nPrice: {listing['price_sek']} SEK\n"
            f"Description:\n{listing['description']}")
    return await ask_json(
        text, EXTRACT_SCHEMA, budget=budget,
        system="Extract hardware specs from a second-hand listing. Never guess: if a spec is not stated, mark it unknown. "
               "If the description contradicts the title, trust the more specific detail and report the contradiction.",
    )


# ---------------------------------------------------------------- 4. Match & vet (deterministic)

def in_stockholm(location):
    loc = (location or "").lower()
    return any(p in loc for p in STOCKHOLM_AREA)


def location_matches(location, city):
    def norm(value):
        value = unicodedata.normalize("NFKD", (value or "").casefold())
        return " ".join(re.findall(r"[a-z0-9]+", "".join(c for c in value if not unicodedata.combining(c))))
    aliases = {"gothenburg": "goteborg", "malmo": "malmo"}
    want = aliases.get(norm(city), norm(city))
    have = aliases.get(norm(location), norm(location))
    if want == "stockholm":
        return in_stockholm(location)
    return bool(want) and bool(re.search(r"(?:^| )" + re.escape(want) + r"(?:$| )", have))


def match(listing, specs, req):
    """Per-requirement verdicts: pass / fail / uncertain, each with a reason."""
    v = {}
    want_cat = req["category"]
    v["type"] = ("pass", specs["category"]) if specs["category"] == want_cat else (
        ("fail", f"{specs['category'].replace('_', ' ')}, not a {want_cat.replace('_', ' ')}"))

    if specs.get("is_for_sale") is False:
        v["type"] = ("fail", "wanted ad (someone else buying), not for sale")
    v["works"] = {"yes": ("pass", "working"), "no": ("fail", "listed as broken / not working")}.get(
        specs.get("working"), ("uncertain", "working condition not confirmed"))
    if not req.get("used_ok", True):
        condition = specs.get("condition", "unknown")
        v["condition"] = {"new": ("pass", "new and unused"), "used": ("fail", "used item; new required")}.get(
            condition, ("uncertain", "new/used condition not confirmed"))

    if req["gpu_min"]:
        need = gpu_score(req["gpu_min"]) or 100
        gpu = specs["gpu"] + (" laptop" if specs.get("gpu_is_laptop_variant") else "")
        have = gpu_score(gpu) if specs["gpu"] else None
        if have is None:
            v["gpu"] = ("uncertain", f"GPU not stated clearly ('{specs['gpu'] or '—'}')")
        elif not req.get("gpu_allow_equivalent", True) and normalize_gpu(gpu) != normalize_gpu(req["gpu_min"]):
            v["gpu"] = ("fail", f"exact GPU {req['gpu_min']} requested; equivalents not allowed")
        elif gpu_score(req["gpu_min"]) is None:
            v["gpu"] = ("uncertain", "requested GPU is not in the benchmark table")
        elif have >= need:
            same = normalize_gpu(gpu) == normalize_gpu(req["gpu_min"])
            v["gpu"] = ("pass", f"{specs['gpu']} ≥ {req['gpu_min']}" + ("" if same else f" (tier {have} vs {need})"))
        else:
            v["gpu"] = ("fail", f"{specs['gpu']} is below {req['gpu_min']} (tier {have} vs {need})")

    if req["ram_gb_min"]:
        r = specs["ram_gb"]
        v["ram"] = ("uncertain", "RAM not stated") if r < 0 else (
            ("pass", f"{r:g} GB") if r >= req["ram_gb_min"] else ("fail", f"only {r:g} GB"))

    if req["storage_gb_min"]:
        need = req["storage_gb_min"] * 0.93  # "1 TB" drives show up as 931-960 GB
        ssd, hdd, unclear = specs["ssd_gb"], specs["hdd_gb"], specs["storage_type_unclear_gb"]
        if req["storage_ssd_required"]:
            if ssd >= need:
                v["storage"] = ("pass", f"{ssd:g} GB SSD")
            elif ssd < 0 and unclear >= need:
                v["storage"] = ("uncertain", f"{unclear:g} GB, SSD or HDD not stated")
            elif ssd < 0 and hdd > 0:
                v["storage"] = ("uncertain", f"{hdd:g} GB 'hårddisk': SSD or HDD? ask the seller")
            elif ssd < 0 and unclear <= 0:
                v["storage"] = ("uncertain", "storage not stated")
            else:
                v["storage"] = ("fail", f"SSD only {max(ssd, 0):g} GB" + (f" (+{hdd:g} GB HDD)" if hdd > 0 else ""))
        else:
            tot = max(ssd, 0) + max(hdd, 0) + unclear
            v["storage"] = ("uncertain", "storage not stated") if tot <= 0 else (
                ("pass", f"{tot:g} GB") if tot >= need else ("fail", f"only {tot:g} GB"))

    p, bmax = listing["price_sek"], req["budget_max_sek"]
    v["price"] = (
        ("pass", f"{p:,} kr asking") if p <= bmax else
        ("negotiable", f"{p:,} kr asking, {p - bmax:,} over budget: worth haggling, offers stay under budget")
        if p <= bmax * NEGOTIABLE_OVER else
        ("fail", f"{p:,} kr asking, far over budget"))

    if location_matches(listing["location"], req.get("city")):
        v["location"] = ("pass", f"pickup in {listing['location']}")
    elif listing.get("shipping") and req["shipping_ok"]:
        v["location"] = ("pass", f"ships from {listing['location']}")
    else:
        v["location"] = ("fail", f"{listing['location']}, no shipping")
    return {k: {"status": s, "reason": r} for k, (s, r) in v.items()}


def market_reference(extracted):
    """Median asking price of listings that look like real matching PCs: our 'market price'."""
    prices = [l["price_sek"] for l, s in extracted if s and s["category"] == "desktop_pc"
              and (gpu_score(s["gpu"]) or 0) >= 95]
    return statistics.median(prices) if len(prices) >= 3 else None


SCAM_WORDS = re.compile(
    r"förskott|banköverföring|bank transfer|western union|paypal friends|endast frakt|only shipping|"
    r"ship only|utomlands|abroad|i'm currently|currently in|whatsapp|gift card|presentkort|handpenning|"
    r"swish i förväg|swisha först|förskottsbetalning|deposit|betala innan|kan ej mötas|cannot meet", re.I)


def risk(listing, specs, market):
    """0-100 scam/risk score with human-readable reasons. Deterministic signals + the LLM's text signals."""
    score, why = 0, []
    s = listing["seller"]
    if market and listing["price_sek"] < 0.55 * market and specs["category"] == "desktop_pc":
        score += 40; why.append(f"price {listing['price_sek']:,} kr is far below market (~{market:,.0f} kr)")
    if s.get("account_age_days", 9999) < 30:
        score += 25; why.append(f"account only {s['account_age_days']} days old")
    if not s.get("num_reviews"):
        score += 10; why.append("seller has no reviews")
    if SCAM_WORDS.search(listing["description"]):
        score += 30; why.append("asks for prepayment / shipping only / off-platform contact")
    for sig in specs.get("risk_signals", [])[:3]:
        score += 8; why.append(sig)
    if specs.get("contradictions"):
        score += 10; why.append("title contradicts description: " + specs["contradictions"])
    return min(score, 100), why


def overall(verdicts, risk_score):
    # "negotiable" (asking a bit over budget) counts like "uncertain": shortlistable, but the deal must come in
    # under budget, and the budget guardrail never lets an offer exceed it
    statuses = ["uncertain" if v["status"] == "negotiable" else v["status"] for v in verdicts.values()]
    if risk_score >= 60:
        return "scam"
    if "fail" in statuses:
        return "reject"
    if "uncertain" in statuses:
        return "uncertain"
    return "match"


# ---------------------------------------------------------------- 5. Rank

def rank_score(listing, specs, verdicts, risk_score, req):
    """Higher is better. Price headroom, spec margin, risk and convenience, all explainable."""
    # rank on the price we expect after haggling, not the asking price: everything gets negotiated
    price = listing["price_sek"] * EXPECTED_AFTER_HAGGLE
    price_pts = 40 * max(0.0, min(1.0, (req["budget_max_sek"] * 1.25 - price) / (req["budget_max_sek"] * 0.6)))
    gs = gpu_score(specs["gpu"]) or 0
    need = gpu_score(req["gpu_min"]) or 100 if req["gpu_min"] else 100
    spec_pts = 25 * max(0.0, min(1.0, (gs - need) / 60 + 0.5)) if gs else 8
    unknown_pen = 8 * sum(1 for v in verdicts.values() if v["status"] == "uncertain" and "budget" not in v["reason"])
    risk_pen = risk_score * 0.4
    near_pts = 10 if location_matches(listing["location"], req.get("city")) else 4
    rep_pts = 5 if (listing["seller"].get("rating") or 0) >= 4.5 else 0
    return round(price_pts + spec_pts + near_pts + rep_pts - unknown_pen - risk_pen, 1)
