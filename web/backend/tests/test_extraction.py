"""Extraction tests. No clinical documents: every fixture here is invented.

Run from web/backend:  python -m pytest tests/ -q
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extraction import channel_map, schema  # noqa: E402


def make_map(*leads) -> str:
    """Build channel-map text: make_map(("LA", 12), ("LB", 8))."""
    tokens = []
    for name, count in leads:
        tokens += [f"{name}{i}" for i in range(1, count + 1)]
    return " ".join(tokens)


class TestChannelMap:
    def test_reads_names_and_counts(self):
        result = channel_map.parse(make_map(("LA", 12), ("LB", 8)))
        assert result.as_counts() == {"LA": 12, "LB": 8}

    def test_ignores_interleaved_channel_numbers(self):
        # The grid alternates contact labels with amplifier channel numbers.
        text = "LA1 LA2 LA3 LA4 LA5 LA6 LA7 LA8\n1 2 3 4 5 6 7 8"
        assert channel_map.parse(text).as_counts() == {"LA": 8}

    def test_rejects_scalp_and_reference_channels(self):
        text = make_map(("LA", 12)) + " FZ Cz C3 C4 EKG1 EKG2 RA5"
        result = channel_map.parse(text)
        assert result.as_counts() == {"LA": 12}
        # C3/C4 and a lone reference marker are surfaced, not silently dropped.
        assert "C" in result.rejected
        assert "RA" in result.rejected

    def test_rejects_a_run_that_does_not_start_at_one(self):
        # Contacts 5..12 only: something was misread, so do not guess a count.
        text = " ".join(f"LX{i}" for i in range(5, 13))
        assert channel_map.parse(text).as_counts() == {}

    def test_picks_the_mixed_case_spelling_on_a_tie(self):
        text = " ".join(f"LOF{i}" for i in range(1, 7))
        text += " " + " ".join(f"LOf{i}" for i in range(7, 13))
        assert "LOf" in channel_map.parse(text).as_counts()


class TestReconcile:
    def test_agreement_is_high_confidence(self):
        model, _ = schema.normalise_model_leads(
            [{"name": "LA", "contacts": 12, "target": "Left Amygdala"}]
        )
        leads, _ = schema.reconcile(model, {"LA": 12})
        assert leads[0].confidence == schema.HIGH
        assert leads[0].sources == ["document", "channel_map"]

    def test_channel_map_wins_a_count_conflict_but_flags_it(self):
        model, _ = schema.normalise_model_leads([{"name": "LB", "contacts": 12}])
        leads, _ = schema.reconcile(model, {"LB": 8})
        assert leads[0].contacts == 8
        assert leads[0].confidence == schema.REVIEW
        assert "12" in leads[0].notes[0] and "8" in leads[0].notes[0]

    def test_proposed_lead_missing_from_the_map_is_kept_and_flagged(self):
        # The case that motivated all of this: a planned lead never implanted.
        model, _ = schema.normalise_model_leads(
            [{"name": "LG", "contacts": 12}, {"name": "LA", "contacts": 12}]
        )
        leads, _ = schema.reconcile(model, {"LA": 12})
        by_name = {l.name: l for l in leads}
        assert by_name["LG"].confidence == schema.REVIEW
        assert "not implanted" in by_name["LG"].notes[0]
        assert by_name["LA"].confidence == schema.HIGH

    def test_lead_only_in_the_channel_map_is_kept(self):
        leads, _ = schema.reconcile([], {"RQ": 12})
        assert leads[0].name == "RQ"
        assert leads[0].contacts == 12
        assert leads[0].confidence == schema.REVIEW

    def test_name_spelling_follows_the_document_not_the_grid(self):
        model, _ = schema.normalise_model_leads([{"name": "LOf", "contacts": 12}])
        leads, _ = schema.reconcile(model, {"LOF": 12})
        assert leads[0].name == "LOf"
        assert leads[0].confidence == schema.HIGH

    def test_missing_count_is_filled_from_the_map(self):
        model, _ = schema.normalise_model_leads([{"name": "LA", "contacts": None}])
        leads, _ = schema.reconcile(model, {"LA": 12})
        assert leads[0].contacts == 12
        assert leads[0].confidence == schema.HIGH


class TestNormalise:
    def test_dimensions_are_one_by_n(self):
        lead = schema.Lead(name="LA", contacts=12)
        assert lead.dimensions == [1, 12]

    def test_bad_type_falls_back_to_depth(self):
        leads, _ = schema.normalise_model_leads([{"name": "LA", "contacts": 8, "type": "X"}])
        assert leads[0].type == "D"

    def test_absurd_contact_count_is_refused(self):
        leads, _ = schema.normalise_model_leads([{"name": "LA", "contacts": 9999}])
        assert leads[0].contacts == 0
        assert leads[0].confidence == schema.REVIEW

    def test_duplicate_names_are_dropped_with_a_warning(self):
        leads, warnings = schema.normalise_model_leads(
            [{"name": "LA", "contacts": 12}, {"name": "LA", "contacts": 8}]
        )
        assert len(leads) == 1 and leads[0].contacts == 12
        assert warnings
