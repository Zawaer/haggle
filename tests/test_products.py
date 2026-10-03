"""Product-agnostic requirements and seller evidence must survive the entire hunt."""
import asyncio
import copy
from unittest.mock import AsyncMock, patch

from haggle import guardrails, mockbay, negotiation, pipeline
from haggle.llm import Budget
from haggle.orchestrator import Hunt
from test_regressions import Base, REQ, SPECS, fixture, move, reading


def rule(key, value="", *, label=None, operator="equals", number=0, unit="", values=None):
    return dict(key=key, label=label or f"{key}: {value or number}", operator=operator,
                value=value, number=number, unit=unit, values=values or [])


def fact(key, value="", *, number=0, unit="", evidence="", known=True):
    return dict(key=key, value=value, number=number, unit=unit, evidence=evidence, known=known)


def request(category, attributes):
    return dict(REQ, category=category, summary=category, gpu_min="", ram_gb_min=0,
                storage_gb_min=0, storage_ssd_required=False, attributes=attributes)


def macbook():
    req = request("laptop", [rule("brand", "Apple"), rule("model", "MacBook Air"),
        rule("chip_family", "Apple M-series", label="Apple Silicon CPU"),
        rule("chip_generation", operator="min", number=1, label="M1 or newer"),
        rule("screen_class", "13-inch", label="13-inch screen")])
    source = "Apple MacBook Air M2, 13-inch. Fully working."
    facts = [fact("brand", "Apple", evidence="Apple"), fact("model", "MacBook Air", evidence="MacBook Air"),
             fact("chip_family", "Apple M-series", evidence="M2"), fact("chip_generation", number=2, evidence="M2"),
             fact("screen_class", "13-inch", evidence="13-inch")]
    specs = dict(SPECS, category="laptop", gpu="", ram_gb=-1, ssd_gb=-1,
                 attributes=pipeline.attribute_facts(facts, req, source))
    listing = dict(id="macbook-test", source="mockbay", title=source, description=source, price_sek=4500,
                   location="Stockholm", shipping=True, seller={"account_age_days": 1000, "rating": 5, "num_reviews": 10})
    return req, listing, specs


class ProductRequirementsTests(Base):
    async def test_any_product_category_can_enter_hunt(self):
        for category in ("laptop", "bicycle", "sofa", "camera", "shoes", "coffee_machine", "violin", "console"):
            with self.subTest(category=category), patch.object(pipeline, "ask_json", AsyncMock(return_value=request(category, []))):
                result = await pipeline.intake(f"{category} under 8000 SEK", Budget(), clarified=True)
                self.assertEqual(result["category"], category)
                self.assertEqual(result["gpu_min"], "")

    async def test_macbook_m1_or_newer_and_13_inch_match(self):
        req, listing, specs = macbook()
        verdicts = pipeline.match(listing, specs, req)
        self.assertEqual(pipeline.overall(verdicts, 0), "match")
        self.assertNotIn("gpu", verdicts)
        self.assertEqual(verdicts["attr_model"]["status"], "pass")
        self.assertEqual(verdicts["attr_chip_generation"]["status"], "pass")

    async def test_wrong_brand_model_chip_and_size_are_rejected(self):
        req, listing, specs = macbook()
        for key, value in (("brand", "Lenovo"), ("model", "MacBook Pro"), ("chip_family", "Intel"), ("screen_class", "15-inch")):
            with self.subTest(key=key):
                other = copy.deepcopy(specs)
                f = next(a for a in other["attributes"] if a["key"] == key)
                f.update(value=value, evidence=value)
                self.assertEqual(pipeline.match(listing, other, req)["attr_" + key]["status"], "fail")
        older = copy.deepcopy(specs)
        next(a for a in older["attributes"] if a["key"] == "chip_generation")["number"] = 0
        self.assertEqual(pipeline.match(listing, older, req)["attr_chip_generation"]["status"], "fail")

    async def test_unquoted_model_output_and_missing_facts_stay_unknown(self):
        req, listing, specs = macbook()
        facts = [fact("chip_family", "Apple M-series", evidence="M2"),
                 fact("screen_class", "13-inch", evidence="13-inch")]
        specs["attributes"] = pipeline.attribute_facts(facts, req, "Laptop in good condition")
        v = pipeline.match(listing, specs, req)
        self.assertTrue(all(x["status"] == "uncertain" for k, x in v.items() if k.startswith("attr_")))
        draft = guardrails.render({"action": "ask"}, req, listing, v, lambda _: False)
        self.assertIn("13-inch screen", draft["message"])
        self.assertIn("Apple Silicon CPU", draft["message"])

    async def test_duplicate_facts_cannot_silently_pick_a_value(self):
        req = request("table", [rule("material", "oak")])
        facts = pipeline.attribute_facts([fact("material", "oak", evidence="oak"),
            fact("material", "pine", evidence="pine")], req, "title oak, description pine")
        self.assertEqual(pipeline.match_attributes({"attributes": facts}, req)["attr_material"]["status"], "uncertain")

    async def test_numeric_bounds_units_and_text_comparisons(self):
        req = request("table", [rule("width", operator="max", number=120, unit="cm"), rule("material", "oak")])
        for width, unit, expected in ((110, "cm", "pass"), (130, "cm", "fail"), (1.1, "m", "uncertain"), (float("nan"), "cm", "uncertain")):
            facts = [fact("width", number=width, unit=unit, evidence="width"), fact("material", "OAK", evidence="oak")]
            v = pipeline.match_attributes({"attributes": facts}, req)
            self.assertEqual(v["attr_width"]["status"], expected)
            self.assertEqual(v["attr_material"]["status"], "pass")
        req = request("camera", [rule("model", "Canon R5", operator="contains")])
        v = pipeline.match_attributes({"attributes": [fact("model", "Canon R50", evidence="Canon R50")]}, req)
        self.assertEqual(v["attr_model"]["status"], "fail")

    async def test_requested_attributes_and_evidence_reach_extraction(self):
        req, listing, specs = macbook()
        # An apparently known extra fact without source evidence must be removed.
        specs["attributes"].append(fact("invented", "yes", evidence="Fully working"))
        ai = AsyncMock(return_value=specs)
        with patch.object(pipeline, "ask_json", ai):
            extracted = await pipeline.extract(listing, Budget(), req)
        self.assertIn("screen_class", ai.call_args.args[0])
        self.assertFalse(any(f["key"] == "invented" for f in extracted["attributes"]))
        self.assertEqual(pipeline.overall(pipeline.match(listing, extracted, req), 0), "match")

    async def test_missing_generic_facts_block_deal(self):
        h, lid = fixture()
        h.req, listing, specs = macbook()
        specs["attributes"] = []
        h.items[lid].update(listing=listing, specs=specs, verdicts=pipeline.match(listing, specs, h.req), state="negotiating", terms_clear=True)
        await h._deal(lid, 4000, "pickup")
        self.assertNotEqual(h.items[lid]["state"], "deal_offered")

    async def test_acceptance_with_new_intel_fact_is_rejected(self):
        h, lid = fixture()
        h.req, listing, specs = macbook()
        listing["id"] = lid
        h.items[lid].update(listing=listing, specs=specs, verdicts=pipeline.match(listing, specs, h.req))
        h.market.reply = {"text": "Accepted at 6500 total. Correction: it has an Intel processor.", "price_sek": 6500}
        response = reading(action="accept", price_sek=6500,
            attributes=[fact("chip_family", "Intel", evidence="Intel processor")])
        with patch.object(negotiation, "read_seller", AsyncMock(return_value=response)):
            await h._negotiate(lid)
        self.assertEqual(h.items[lid]["state"], "dropped")
        self.assertEqual(h.items[lid]["verdicts"]["attr_chip_family"]["status"], "fail")

    async def test_seller_can_resolve_or_retract_a_generic_requirement(self):
        h, lid = fixture(); h.req, listing, specs = macbook()
        specs["attributes"] = [a for a in specs["attributes"] if a["key"] != "screen_class"]
        h.items[lid].update(listing=listing, specs=specs, verdicts=pipeline.match(listing, specs, h.req))
        learned = pipeline.attribute_facts([fact("screen_class", "13-inch", evidence="13-inch")], h.req, "It is 13-inch")
        await h._apply_learned(lid, {"attributes": learned})
        self.assertEqual(h.items[lid]["verdicts"]["attr_screen_class"]["status"], "pass")
        retracted = pipeline.attribute_facts([fact("screen_class", known=False, evidence="not sure")], h.req, "Actually I am not sure")
        await h._apply_learned(lid, {"attributes": retracted})
        self.assertEqual(h.items[lid]["verdicts"]["attr_screen_class"]["status"], "uncertain")

    async def test_complete_non_computer_hunt_with_controlled_models(self):
        req = request("table", [rule("material", "oak")])
        listing = dict(id="table-1", source="mockbay", title="Oak dining table", description="Solid oak, usable, no damage.",
                       price_sek=2000, location="Stockholm", shipping=False,
                       seller={"account_age_days": 1000, "num_reviews": 20, "rating": 5})
        specs = dict(SPECS, category="table", gpu="", attributes=[fact("material", "oak", evidence="oak")])
        h = Hunt("Oak dining table under 8000 SEK, pickup Stockholm")
        # Use an isolated transport with controlled seller replies; no external message is sent.
        from test_regressions import Market
        h.market = Market()
        h.market.reply = {"text": "I accept 1800 total for the oak table, pickup Stockholm.", "price_sek": 1800}
        with patch.object(pipeline, "intake", AsyncMock(return_value=req)), \
             patch.object(pipeline, "extract", AsyncMock(return_value=specs)), \
             patch.object(h, "_search", AsyncMock(return_value=[listing])), \
             patch.object(negotiation, "buyer_turn", AsyncMock(return_value=move(offer_sek=1800))), \
             patch.object(negotiation, "read_seller", AsyncMock(return_value=reading(action="accept", price_sek=1800))):
            await h.run()
            self.assertEqual(h.phase, "awaiting_approval")
            await h.approve([listing["id"]])
            self.assertEqual(h.phase, "awaiting_confirmation")
            await h.confirm(listing["id"])
        self.assertEqual(h.items[listing["id"]]["state"], "confirmed")

    async def test_alternative_attributes_and_explicit_repair_items(self):
        req = request("bicycle", [rule("color", operator="one_of", values=["red", "blue"])])
        for color, expected in (("red", "pass"), ("BLUE", "pass"), ("green", "fail")):
            v = pipeline.match_attributes({"attributes": [fact("color", color, evidence=color)]}, req)
            self.assertEqual(v["attr_color"]["status"], expected)
        req, listing, specs = macbook()
        req["working_required"] = False
        specs["working"] = "no"
        self.assertEqual(pipeline.overall(pipeline.match(listing, specs, req), 0), "match")

    async def test_mockbay_public_product_details_are_available_to_buyer(self):
        listing = mockbay.normalize({"id": "air", "title": "MacBook Air", "description": "Working laptop", "price": 4500,
            "attributes": {"Processor": "Apple M1", "Screen": "13-inch", "Märke": "Apple"}, "condition": "Used"})
        self.assertIn("Processor: Apple M1", listing["description"])
        self.assertIn("Screen: 13-inch", listing["description"])
        self.assertIn("Apple M1", negotiation.seller_system(mockbay.full("air")))
        self.assertIsNone(mockbay.stock_photo({"title": "Gaming chair", "description": "For a gaming setup"}))
