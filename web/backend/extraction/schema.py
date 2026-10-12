"""Extraction result shape, validation, and reconciliation of the two sources.

Two things look at the same document: a model reading the lead table, and a
regex reading the channel map. This module decides what to believe when they
disagree, and never resolves a disagreement silently — every conflict comes out
as a lead flagged ``review`` with a note saying what the two sources said.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

VALID_TYPES = ("D", "G", "S")  # depth, grid, strip — matches VoxTool's lead types

HIGH = "high"
REVIEW = "review"


@dataclass
class Lead:
    name: str
    contacts: int
    type: str = "D"
    target: str = ""
    confidence: str = HIGH
    sources: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def dimensions(self) -> list[int]:
        """VoxTool stores a lead as rows x columns; a depth is a single column."""
        return [1, self.contacts]

    def to_json(self) -> dict:
        d = asdict(self)
        d["dimensions"] = self.dimensions
        return d


@dataclass
class ExtractionResult:
    leads: list[Lead] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    document: dict = field(default_factory=dict)
    provider: str = "none"

    @property
    def needs_review(self) -> int:
        return sum(1 for l in self.leads if l.confidence == REVIEW)

    def to_json(self) -> dict:
        return {
            "leads": [l.to_json() for l in self.leads],
            "warnings": self.warnings,
            "document": self.document,
            "provider": self.provider,
            "needs_review": self.needs_review,
        }


def _clean_type(value) -> str:
    t = str(value or "D").strip().upper()[:1]
    return t if t in VALID_TYPES else "D"


def _clean_contacts(value):
    """Contact counts must be small positive integers or we do not trust them."""
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= 64 else None


def normalise_model_leads(raw) -> tuple[list[Lead], list[str]]:
    """Coerce whatever the model returned into Leads, dropping anything unusable."""
    leads: list[Lead] = []
    warnings: list[str] = []
    if not isinstance(raw, list):
        return leads, ["Model did not return a list of leads."]

    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        key = name.upper()
        if key in seen:
            warnings.append(f"Model listed {name} more than once; kept the first.")
            continue
        seen.add(key)

        contacts = _clean_contacts(entry.get("contacts"))
        lead = Lead(
            name=name,
            contacts=contacts or 0,
            type=_clean_type(entry.get("type")),
            target=str(entry.get("target") or "").strip(),
            sources=["document"],
        )
        if contacts is None:
            lead.confidence = REVIEW
            lead.notes.append(
                f"No usable contact count in the document (model said "
                f"{entry.get('contacts')!r})."
            )
        leads.append(lead)
    return leads, warnings


def reconcile(model_leads: list[Lead], channel_counts: dict[str, int]) -> tuple[list[Lead], list[str]]:
    """Cross-check the model's reading against the channel map.

    The channel map wins on contact counts because it enumerates what was
    actually wired up, but the model's spelling of the name wins because that is
    the label the clinical team uses elsewhere (``LOf`` in the lead table versus
    ``LOF`` in the grid). Anything that appears in only one source is kept and
    flagged rather than dropped: a lead missing from the channel map is usually
    a proposed target that was never implanted, and that is a judgement for the
    person reviewing, not for us.
    """
    warnings: list[str] = []
    by_key = {l.name.upper(): l for l in model_leads}
    channel_by_key = {k.upper(): v for k, v in channel_counts.items()}
    # Keep the channel map's own spelling so we can name leads it alone found.
    channel_names = {k.upper(): k for k in channel_counts}

    out: list[Lead] = []

    unmatched_channel = set(channel_by_key) - set(by_key)

    for key, lead in by_key.items():
        mapped = channel_by_key.get(key)
        if mapped is None:
            if channel_counts:
                lead.confidence = REVIEW
                twin = _near_match(key, unmatched_channel)
                if twin:
                    lead.notes.append(
                        f"Not in the channel map, but {channel_names[twin]} is and "
                        f"uses the same letters — one of the two is probably a typo."
                    )
                else:
                    lead.notes.append(
                        "Listed in the document but absent from the channel map, so "
                        "it may be a proposed lead that was not implanted."
                    )
            out.append(lead)
            continue

        lead.sources.append("channel_map")
        if lead.contacts == mapped:
            lead.confidence = HIGH
        elif lead.contacts == 0:
            lead.contacts = mapped
            lead.confidence = HIGH
            lead.notes.append(f"Contact count taken from the channel map ({mapped}).")
        elif lead.contacts > mapped:
            # A channel map cannot list more contacts than an electrode has, but
            # it can list fewer: with 256 amplifier channels and 22 twelve-contact
            # leads, the last leads get truncated. The electrode still has all
            # twelve and all twelve are visible on the CT, so the larger number
            # is the one to localise against.
            lead.notes.append(
                f"{lead.contacts} contacts on the electrode but only {mapped} "
                f"wired to the amplifier; using {lead.contacts} since the rest "
                f"are still visible on the scan."
            )
            lead.confidence = REVIEW
        else:
            lead.notes.append(
                f"Document says {lead.contacts} contacts, channel map says "
                f"{mapped}. Using {mapped}."
            )
            lead.contacts = mapped
            lead.confidence = REVIEW
        out.append(lead)

    for key, count in channel_by_key.items():
        if key in by_key:
            continue
        twin = _near_match(key, set(by_key) - set(channel_by_key))
        note = (
            f"In the channel map but not the lead table. {by_key[twin].name} is in "
            f"the table and uses the same letters — one of the two is probably a typo."
            if twin
            else "Found in the channel map but not in the lead table; target unknown."
        )
        out.append(
            Lead(
                name=channel_names[key],
                contacts=count,
                sources=["channel_map"],
                confidence=REVIEW,
                notes=[note],
            )
        )

    out.sort(key=lambda l: l.name.upper())
    if not model_leads and channel_counts:
        warnings.append(
            "No lead table was read from the document, so every lead below came "
            "from the channel map and has no anatomical target."
        )
    return out, warnings


def _near_match(name: str, candidates) -> str | None:
    """Find a candidate that is the same letters in a different order.

    Documents really do contain ``RFp`` in the lead table and ``RPf`` in the
    channel map. Those are one lead, but merging them automatically would be
    guessing, so we only point the pair out and let the reviewer decide.
    """
    key = sorted(name.upper())
    for other in candidates:
        if other != name and sorted(other.upper()) == key:
            return other
    return None
