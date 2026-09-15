"""Document in, reviewed lead definitions out.

The order matters. The channel map is parsed first and unconditionally, because
it works with no model installed and is the thing we trust on contact counts.
The model is then asked for the parts a regex cannot supply — which lead is
which anatomical target, and the contact counts for any lead that never made it
into the channel map. Finally the two are reconciled, and anything they disagree
about is surfaced rather than resolved quietly.
"""
from __future__ import annotations

from . import channel_map, documents, providers, schema


def run(path: str, provider: str = "none", model: str | None = None) -> schema.ExtractionResult:
    doc = documents.load(path)
    text = doc.text

    result = schema.ExtractionResult(provider=provider or "none")
    result.document = doc.summary()

    if doc.scanned_pages:
        result.warnings.append(
            f"No text could be read from page(s) "
            f"{', '.join(str(p) for p in doc.scanned_pages)} — these look like "
            f"scans or photographs. Anything written only there was not seen."
        )
    if not text.strip():
        result.warnings.append(
            "The document has no readable text at all. It is probably a scan, "
            "which needs OCR before it can be used."
        )
        return result

    mapped = channel_map.parse(text)
    if mapped.rejected:
        listed = ", ".join(
            f"{name} ({', '.join(str(n) for n in nums)})"
            for name, nums in sorted(mapped.rejected.items())
        )
        result.warnings.append(
            f"Contact-like labels that do not form a complete lead were ignored: "
            f"{listed}. These are usually scalp or reference channels."
        )

    model_leads: list[schema.Lead] = []
    if provider and provider != "none":
        try:
            raw = providers.extract(provider, text, model=model)
        except providers.ProviderUnavailable as e:
            result.warnings.append(f"{e} Falling back to the channel map alone.")
            result.provider = "none"
        else:
            model_leads, warns = schema.normalise_model_leads(raw)
            result.warnings.extend(warns)

    leads, warns = schema.reconcile(model_leads, mapped.as_counts())
    result.leads = leads
    result.warnings.extend(warns)

    if not leads:
        result.warnings.append(
            "No leads were found. Check that this document contains a lead table "
            "or a channel map."
        )
    return result
