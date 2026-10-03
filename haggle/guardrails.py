"""Seller-facing proposals rendered from validated data, never unvalidated model prose."""
import math


def money(value, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("price must be a finite number")
    if value <= 0 or value > maximum:
        raise ValueError("price must be positive and within budget")
    rounded = round(value, 2)
    if rounded <= 0 or rounded > maximum:
        raise ValueError("rounded price must be positive and within budget")
    return rounded


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
    out.update(message=text, offer_sek=price, claims_competing_offer_sek=claim,
               private_thoughts=out.get("private_thoughts", ""))
    return out
