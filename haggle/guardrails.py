"""Seller-facing proposals: the model writes the wording, code validates it.

Prices, competing offers and commitments come from validated data. The model's message is sent only if
code can check it (every amount is the validated offer or a verified competing offer, no commitment to buy,
no payment talk, no contact details); otherwise the message is rendered from a fixed template.
"""
import math
import re


def money(value, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("price must be a finite number")
    if value <= 0 or value > maximum:
        raise ValueError("price must be positive and within budget")
    rounded = round(value, 2)
    if rounded <= 0 or rounded > maximum:
        raise ValueError("rounded price must be positive and within budget")
    return rounded


_HW_BEFORE = {"rtx", "gtx", "rx", "ryzen", "core", "radeon", "geforce", "arc", "i3", "i5", "i7", "i9", "r5", "r7", "r9",
              "ddr4", "ddr5", "m.2", "nvme", "pcie", "gen"}
_HW_AFTER = re.compile(r"^\s*(gb|tb|mb|gig|w|hz|mhz|ghz|mm|tum|inch|\"|fps|p\b|k\b(?!r))", re.I)
_NUM = re.compile(r"(?<![\w.-])(\d{1,3}(?:[ \u00a0.,]\d{3})+|\d+)(\s*k\b(?!r))?", re.I)
_FORBIDDEN = re.compile(
    r"jag köper|vi köper|köper jag|köper vi|jag tar (den|det)|vi tar (den|det)|tar jag (den|det)|tar vi (den|det)|"
    r"affär klar|det är en affär|köpt!|"
    r"i'?ll buy|i will buy|we'?ll buy|i'?ll take it|we have a deal|it'?s a deal|deal!|sold!|"
    r"swish|förskott|handpenning|deposit|prepay|pay (now|first|upfront|in advance)|betala (nu|först|i förväg)|"
    r"bank ?transfer|banköverföring|paypal|https?://|www\.|@|\+?\d[\d -]{7,}\d", re.I)
_COMPETING = re.compile(r"annan säljare|andra säljare|annat bud|annat erbjudande|another seller|other seller|"
                        r"another offer|other offer|competing", re.I)


def amounts(text):
    """Money amounts in a chat message (spec numbers like 'RTX 3060' or '16 GB' are skipped)."""
    found = []
    for m in _NUM.finditer(text):
        raw, k = m.group(1), m.group(2)
        before = text[:m.start()].split()[-1].lower().strip("(-:,") if text[:m.start()].split() else ""
        if before in _HW_BEFORE or _HW_AFTER.match(text[m.end():]) or text[m.start() - 1:m.start()].isalpha():
            continue
        value = int(re.sub(r"[ \u00a0.,]", "", raw)) * (1000 if k else 1)
        if 1990 <= value <= 2035 and raw.isdigit() and not re.match(r"^\s*(kr|sek|:-|kronor)", text[m.end():], re.I):
            continue  # a year ("köpt 2021"), not a price
        if value >= 300:  # smaller numbers are counts, ages, sizes
            found.append(value)
    return found


def check_prose(text, action, price, claim):
    """None if the model's message is safe to send as written, else the reason it isn't."""
    if not text or len(text) > 700:
        return "empty or too long"
    if _FORBIDDEN.search(text):
        return "commitment, payment or contact wording"
    # exact match: a validated 6 500.5 kr offer written as "6500" is a different price -> template
    allowed = {price} if action == "offer" and price else set()
    if claim:
        allowed.add(claim)
    nums = amounts(text)
    bad = [n for n in nums if n not in allowed]
    if bad:
        return f"amount {bad[0]:,} kr is not the validated offer".replace(",", " ")
    if action == "offer" and price not in nums:
        return "offer amount missing from the message"
    if claim and claim not in nums:
        return "verified competing offer missing from the message"
    if _COMPETING.search(text) and not claim:
        return "mentions another offer that isn't verified"
    return None


def render(proposal, req, listing, verdicts, claim_ok):
    """The model chooses strategy; code constructs monetary and commitment wording.

    Arbitrary generated prose cannot be proven safe using regular expressions.
    Free-text explanations and logistical promises are therefore never sent as commitments.
    """
    out = dict(proposal)
    action = out.get("action")
    if action not in ("offer", "accept", "ask", "walk_away"):
        raise ValueError("invalid negotiation action")
    sv = listing.get("_lang") == "sv"
    price = money(out.get("offer_sek"), req["budget_max_sek"]) if action in ("offer", "accept") else 0
    claim = out.get("claims_competing_offer_sek") or 0
    if claim:
        money(claim, float("inf"))
        if not claim_ok(claim):
            raise ValueError("unverified competing offer")
    questions = {
        "type": ("Vad är det för vara och modell?", "What is the product type and model?"),
        "gpu": ("Vilket exakt grafikkort sitter i?", "What is the exact GPU model?"),
        "ram": ("Hur mycket RAM har den?", "How much RAM does it have?"),
        "storage": ("Vilken lagring finns, SSD eller HDD och hur många GB?", "What storage does it have: SSD or HDD, and how many GB?"),
        "works": ("Fungerar allt utan fel?", "Is everything working without faults?"),
        "condition": ("Är den ny och oanvänd?", "Is it new and unused?"),
        "location": ("Var kan den hämtas, och kan den skickas?", "Where can it be collected, and can it be shipped?"),
    }
    unknown = [questions[k][0 if sv else 1] for k, v in verdicts.items()
               if v["status"] == "uncertain" and k in questions]
    for key, verdict in verdicts.items():
        if key.startswith("attr_") and verdict["status"] == "uncertain":
            label = verdict.get("label", key[5:])
            unknown.append(f"Kan du bekräfta följande krav: {label}?" if sv else f"Can you confirm this requirement: {label}?")
    p = f"{price:,.2f}".rstrip("0").rstrip(".").replace(",", " ")
    if action == "offer":
        text = f"Kan du tänka dig {p} kr totalt, inklusive eventuell frakt?" if sv else f"Would you consider {p} SEK total, including any shipping?"
        if unknown:
            text += " " + " ".join(unknown)
    elif action == "accept":
        text = (f"{p} kr totalt fungerar preliminärt, i väntan på min klients bekräftelse. Ingen förskottsbetalning."
                if sv else f"{p} SEK total works provisionally, pending my client's confirmation. No advance payment.")
    elif action == "ask":
        text = " ".join(unknown) or ("Kan du bekräfta skick, leverans och totalpris inklusive eventuell frakt?" if sv
                                           else "Can you confirm the condition, handover and total price including any shipping?")
    else:
        text = "Tack för din tid, men vi går inte vidare med den här affären." if sv else "Thanks for your time, but we won't proceed with this deal."
    if claim and action in ("offer", "ask"):
        p = f"{claim:,.2f}".rstrip("0").rstrip(".").replace(",", " ")
        text += f" En annan säljare erbjuder {p} kr." if sv else f" Another seller has offered {p} SEK."
    # the model's own wording when code can verify it (accept always uses the provisional template)
    prose = (proposal.get("message") or "").strip()
    reason = check_prose(prose, action, price, claim) if action in ("offer", "ask", "walk_away") else "accept uses the template"
    out["wording"] = "checked" if reason is None else "template"
    if reason is None:
        text = prose
    elif prose and action != "accept":
        out["wording_rejected"] = reason
    out.update(message=text, offer_sek=price, claims_competing_offer_sek=claim,
               private_thoughts=out.get("private_thoughts", ""))
    return out
