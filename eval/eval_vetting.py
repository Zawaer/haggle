"""Evaluate steps 3-4 (extract + match & vet) against the dataset's hidden ground truth.

For every listing: run Gemini extraction, then our deterministic matcher and risk scorer, and compare
with `hidden.expected_verdict`. The ground truth ignores price (it's about specs, legitimacy and
logistics), so price is left out of the verdict here.

    .venv/bin/python -m eval.eval_vetting            # prints accuracy, confusion and mismatches
"""
import asyncio
import json
import sys
from collections import Counter

from haggle import marketplace, pipeline
from haggle.llm import Budget

REQ = {
    "category": "desktop_pc", "budget_max_sek": 8000, "target_price_sek": 7000, "gpu_min": "RTX 3060",
    "gpu_allow_equivalent": True, "ram_gb_min": 16, "storage_gb_min": 1000, "storage_ssd_required": True,
    "city": "Stockholm", "shipping_ok": True, "used_ok": True,
}
# our verdicts -> ground-truth labels ("near_miss" and "reject" are both a no for the buyer)
TO_TRUTH = {"match": "match", "uncertain": "uncertain", "reject": "reject", "scam": "scam"}


def truth(l):
    t = l["hidden"]["expected_verdict"]
    return "reject" if t == "near_miss" else t


async def main():
    b = Budget(cap=200)
    ls = marketplace.listings()
    pub = [marketplace.public_view(l) for l in ls]
    specs = await asyncio.gather(*(pipeline.extract(p, b) for p in pub))
    market = pipeline.market_reference(list(zip(pub, specs)))
    rows, conf = [], Counter()
    for l, p, s in zip(ls, pub, specs):
        v = pipeline.match(p, s, REQ)
        v.pop("price", None)
        r, why = pipeline.risk(p, s, market)
        ours = pipeline.overall(v, r)
        conf[(truth(l), ours)] += 1
        rows.append((l, ours, v, r, why, s))
    ok = sum(1 for l, ours, *_ in rows if truth(l) == ours)
    scams = [x for x in rows if truth(x[0]) == "scam"]
    caught = sum(1 for x in scams if x[1] == "scam")
    false_alarms = sum(1 for x in rows if x[1] == "scam" and truth(x[0]) != "scam")
    good = [x for x in rows if truth(x[0]) == "match"]
    good_kept = sum(1 for x in good if x[1] in ("match", "uncertain"))
    print(f"verdict accuracy: {ok}/{len(rows)} = {ok/len(rows):.0%}")
    print(f"scams caught: {caught}/{len(scams)}, false scam alarms: {false_alarms}")
    print(f"real matches kept (match or uncertain): {good_kept}/{len(good)}")
    print(f"market ref {market}, LLM calls {b.calls}")
    print("confusion (truth -> ours):", dict(conf))
    print("\nMISMATCHES:")
    for l, ours, v, r, why, s in rows:
        if truth(l) != ours:
            bad = {k: x["reason"] for k, x in v.items() if x["status"] != "pass"}
            print(f"- {l['id']} truth={l['hidden']['expected_verdict']} ours={ours} risk={r} {l['title'][:50]!r}")
            print(f"    non-pass: {bad}  risk: {why[:3]}")
            print(f"    extracted: gpu={s['gpu']!r} ram={s['ram_gb']} ssd={s['ssd_gb']} hdd={s['hdd_gb']} "
                  f"unclear={s['storage_type_unclear_gb']} cat={s['category']}")
            print(f"    truth note: {l['hidden']['notes'][:160]}")
    json.dump({"accuracy": ok / len(rows), "scams_caught": caught, "scams_total": len(scams),
               "false_scam_alarms": false_alarms, "matches_kept": good_kept, "matches_total": len(good)},
              open("eval/vetting_result.json", "w"), indent=1)


if __name__ == "__main__":
    asyncio.run(main())
