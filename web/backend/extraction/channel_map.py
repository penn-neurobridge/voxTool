"""Recover lead names and contact counts from an amplifier channel map.

Implant documents usually contain, somewhere near the back, a grid that maps
every contact to an amplifier channel: ``LA1 LA2 ... LA12 LB1 ... LB8``. That
grid is mechanical — it enumerates every contact that was actually recorded, in
full, with no prose around it. So it can be parsed with a regex and needs no
model at all.

That matters more than it first appears. Implant documents routinely contain a
*proposed* layout as well as the final one, and they disagree: a planned lead
gets dropped in theatre, or a different target is added. A model reading the
document has no principled way to know which table won. The channel map does,
because it reflects what was wired up. So we use it as the check on whatever the
model returns, rather than as one more opinion.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

# A contact token: letters then digits, e.g. LA12, ROf3, RC1.
_TOKEN = re.compile(r"\b([A-Za-z]{1,4})(\d{1,2})\b")

# Scalp, reference and physiological channels share the grid with the depths but
# are not electrodes we localise.
_NON_DEPTH = {
    "EKG", "ECG", "EMG", "EOG", "REF", "GND", "DC", "TRIG",
    "FZ", "CZ", "PZ", "OZ", "FP", "AF", "PO",
}

# Below this, a run of numbers is more likely to be scalp contacts or a stray
# reference marker than a depth lead. The shortest real depth here is 8.
_MIN_CONTACTS = 4


@dataclass
class ChannelMapLead:
    name: str
    contacts: int
    numbers: list[int]

    @property
    def is_contiguous(self) -> bool:
        return sorted(self.numbers) == list(range(1, self.contacts + 1))


@dataclass
class ChannelMapResult:
    leads: list[ChannelMapLead]
    rejected: dict[str, list[int]]  # prefix -> numbers seen, for human review
    # Looks like a real lead but has a hole in its numbering, which in practice
    # means a mistyped label in the grid rather than a scalp channel. Reported
    # separately so the warning can say which contact is missing instead of
    # calling it a reference electrode.
    gapped: dict[str, list[int]] = field(default_factory=dict)

    def as_counts(self) -> dict[str, int]:
        return {lead.name: lead.contacts for lead in self.leads}


def parse(text: str) -> ChannelMapResult:
    """Harvest lead names and contact counts from contact tokens in `text`."""
    # Case varies within a single document (LOf / LOF / Lof all appear), so group
    # case-insensitively and decide the canonical spelling afterwards.
    numbers_by_key: dict[str, set[int]] = defaultdict(set)
    spellings: dict[str, Counter] = defaultdict(Counter)

    for prefix, digits in _TOKEN.findall(text):
        key = prefix.upper()
        if key in _NON_DEPTH:
            continue
        numbers_by_key[key].add(int(digits))
        spellings[key][prefix] += 1

    leads: list[ChannelMapLead] = []
    rejected: dict[str, list[int]] = {}
    gapped: dict[str, list[int]] = {}

    for key, numbers in numbers_by_key.items():
        ordered = sorted(numbers)
        highest = ordered[-1]
        # Require a run starting at 1 with nothing missing. C3/C4 (scalp) and a
        # lone reference marker like RA5 both fail this, which is what we want:
        # they surface as rejected rather than inventing a 4- or 5-contact lead.
        contiguous = ordered == list(range(1, highest + 1))
        if contiguous and highest >= _MIN_CONTACTS:
            leads.append(
                ChannelMapLead(
                    name=_canonical(spellings[key]),
                    contacts=highest,
                    numbers=ordered,
                )
            )
        elif highest >= _MIN_CONTACTS and 1 in numbers:
            # Starts at 1 and is long enough to be a lead, but something is
            # missing in the middle: a mistyped cell, not a scalp channel.
            gapped[_canonical(spellings[key])] = ordered
        else:
            rejected[_canonical(spellings[key])] = ordered

    # Fill in any lead the numbered pass did not accept. Exclusion is by
    # accepted lead, not by "was seen with a digit anywhere": a document that
    # notes `Ref: LF10` would otherwise disqualify LF from the unnumbered count
    # on the strength of the reference marker alone. A normal numbered grid has
    # no bare-label rows, so this contributes nothing there.
    accepted = {l.name.upper() for l in leads}
    for name, count in _unnumbered_counts(text).items():
        if name.upper() in accepted or count < _MIN_CONTACTS:
            continue
        leads.append(
            ChannelMapLead(name=name, contacts=count, numbers=list(range(1, count + 1)))
        )
        rejected.pop(name, None)
        gapped.pop(name, None)

    leads.sort(key=lambda l: l.name)
    return ChannelMapResult(leads=leads, rejected=rejected, gapped=gapped)


# A cell holding only a lead label, with no contact number after it.
_BARE = re.compile(r"^[A-Za-z]{1,4}$")

# A grid row has one cell per amplifier channel, so it is wide. Narrower rows
# are prose or lead-table rows and must not be counted.
_MIN_GRID_CELLS = 8


def _unnumbered_counts(text: str) -> Counter:
    """Count repeats in grids that omit the contact number.

    One site writes the grid as ``LI LI LI ... LA LA LA`` — the label repeated
    once per contact, with the number implied by the column. Counting repeats
    recovers the contact count, but only on rows that are almost entirely bare
    labels: otherwise the single ``LI`` in the lead table, or a lead name in a
    sentence, would be counted as another contact.
    """
    counts: Counter = Counter()
    for line in text.splitlines():
        cells = [c.strip() for c in line.split("\t") if c.strip()]
        if len(cells) < _MIN_GRID_CELLS:
            continue
        bare = [c for c in cells if _BARE.match(c)]
        if len(bare) < 0.9 * len(cells):
            continue
        for cell in bare:
            if cell.upper() not in _NON_DEPTH:
                counts[cell] += 1
    return counts


def _canonical(counter: Counter) -> str:
    """Most frequent spelling, ties broken by the more specific capitalisation.

    ``LOf`` beats ``LOF`` on a tie: mixed case is a deliberate choice by whoever
    typed it, whereas all-caps is what a form or a careless paste produces.
    """
    best = max(counter.items(), key=lambda kv: (kv[1], sum(c.islower() for c in kv[0])))
    return best[0]
