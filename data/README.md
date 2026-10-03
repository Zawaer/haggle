# Mock marketplace dataset

`listings.json` holds 42 hand-written second-hand listings from Blocket, Tradera and Facebook Marketplace, built for the demo request: *a gaming PC under 8,000 SEK with at least an RTX 3060 or equivalent, 16 GB RAM and a 1 TB SSD, picked up in Stockholm or shipped*.

The fields at the top level are what the buyer agent sees. Everything under `hidden` is ground truth for the seller simulator and for evals, and must never be shown to the agent:

- `true_specs`: the real specs. These are all null for scams, because the item doesn't exist.
- `min_price_sek`: the seller's real floor. It is null for the "Köpes" (wanted) ad.
- `personality` / `language`: how the simulated seller talks and negotiates.
- `expected_verdict`: judges specs, legitimacy and logistics, but not price. Whether a deal can get under budget depends on `min_price_sek`: some matches have a floor above 8000.
- `notes`: what the listing tests.

Verdicts: 12 match, 10 near_miss, 9 reject, 6 uncertain, 5 scam.
