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

    def test_truncated_recording_keeps_the_electrode_count(self):
        # 256 amplifier channels across 22 twelve-contact leads means the last
        # leads get fewer channels than they have contacts. The contacts still
        # exist on the CT, so the table's larger number is the one to localise.
        model, _ = schema.normalise_model_leads([{"name": "RL", "contacts": 12}])
        leads, _ = schema.reconcile(model, {"RL": 8})
        assert leads[0].contacts == 12
        assert leads[0].confidence == schema.REVIEW
        assert "wired to the amplifier" in leads[0].notes[0]

    def test_channel_map_wins_when_it_has_more_contacts(self):
        # The grid cannot enumerate contacts that do not exist, so a larger
        # count there means the table is wrong.
        model, _ = schema.normalise_model_leads([{"name": "LB", "contacts": 8}])
        leads, _ = schema.reconcile(model, {"LB": 12})
        assert leads[0].contacts == 12
        assert leads[0].confidence == schema.REVIEW

    def test_transposed_name_is_pointed_out_rather_than_merged(self):
        # A real document had RFp in the lead table and RPf in the channel map.
        model, _ = schema.normalise_model_leads([{"name": "RFp", "contacts": 12}])
        leads, _ = schema.reconcile(model, {"RPf": 12})
        assert len(leads) == 2, "must not silently merge two differently spelled leads"
        assert all("typo" in " ".join(l.notes) for l in leads)

    def test_gap_in_the_grid_is_separated_from_scalp_channels(self):
        # LI3 mistyped as a second LI4 in a real document.
        text = " ".join(f"LI{i}" for i in [1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12])
        result = channel_map.parse(text + " C3 C4")
        assert "LI" in result.gapped, "a hole mid-lead is a typo, not a scalp channel"
        assert "C" in result.rejected
        assert "LI" not in result.as_counts()

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


class TestUnnumberedGrid:
    """One site writes the grid as the bare label repeated once per contact."""

    def test_counts_repeats_when_there_are_no_contact_numbers(self):
        grid = "\t".join(["LI"] * 12 + ["LA"] * 4)
        grid += "\n" + "\t".join(["LA"] * 8 + ["LB"] * 8)
        counts = channel_map.parse(grid).as_counts()
        assert counts == {"LI": 12, "LA": 12, "LB": 8}

    def test_lead_table_rows_are_not_counted_as_contacts(self):
        # The lead table mentions LI once; only the wide grid row counts.
        text = "LI\tLeft Temporal Pole\t8\tBlue 8\t12\n"
        text += "\t".join(["LI"] * 12 + ["LA"] * 4)
        assert channel_map.parse(text).as_counts()["LI"] == 12

    def test_a_reference_marker_does_not_disqualify_a_lead(self):
        # "Ref: LF10" must not stop LF being counted from the unnumbered grid.
        text = "Ref: LF10\nGr: LU9\n"
        text += "\t".join(["LF"] * 12 + ["LU"] * 4) + "\n"
        text += "\t".join(["LU"] * 8 + ["LF"] * 8)
        counts = channel_map.parse(text).as_counts()
        assert counts == {"LF": 20, "LU": 12}

    def test_a_normal_numbered_grid_is_unaffected(self):
        text = " ".join(f"LA{i}" for i in range(1, 13))
        assert channel_map.parse(text).as_counts() == {"LA": 12}
