"""Where the language model runs.

Everything here is optional. ``none`` is a real, useful provider: the channel
map alone already yields lead names and contact counts, so extraction degrades
to "correct but without anatomical targets" rather than to failure when no model
is installed. That property is deliberate — the desktop app must not depend on a
model being present.

``ollama`` talks to a model running on the same machine, so no patient document
leaves the computer. urllib is used rather than requests to avoid adding a
dependency to the frozen desktop backend.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

OLLAMA_HOST = os.environ.get("VOXTOOL_OLLAMA_HOST", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.environ.get("VOXTOOL_LLM_MODEL", "qwen2.5:7b-instruct")

# Constrained decoding: Ollama accepts a JSON schema and will only emit tokens
# that keep the output valid against it. That removes malformed JSON as a
# failure mode entirely, leaving only wrong values — which the channel-map
# cross-check and the human review screen are there to catch.
LEADS_SCHEMA = {
    "type": "object",
    "properties": {
        "leads": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "target": {"type": "string"},
                    "contacts": {"type": "integer"},
                    "type": {"type": "string", "enum": ["D", "G", "S"]},
                },
                "required": ["name", "contacts"],
            },
        }
    },
    "required": ["leads"],
}

SYSTEM_PROMPT = """\
You read stereo-EEG implant documents and return the list of implanted leads.

Rules:
- Return one entry per electrode lead, not per contact.
- "name" is the short label used for the lead, such as LA, LB, ROf. Copy the
  document's spelling and capitalisation exactly.
- "target" is the anatomical target in the document's own words, such as
  "Left Amygdala". Leave it empty if the document does not say.
- "contacts" is how many contacts that lead has.
- "type" is D for a depth electrode, G for a grid, S for a strip. Use D if the
  document does not say.
- A document may show a PROPOSED layout as well as the final implanted one, and
  they may differ. Always describe the final implanted layout. Ignore any
  section labelled proposed, planned, or crossed out.
- Do not include scalp electrodes (Fz, Cz, C3, C4), EKG, reference or ground.
- Never invent a lead or a contact count. Omit anything the document does not
  state.
"""


class ProviderUnavailable(RuntimeError):
    """Raised when the configured provider cannot be reached."""


def available_providers() -> dict[str, bool]:
    return {"none": True, "ollama": ollama_available()}


def ollama_available() -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def ollama_models() -> list[str]:
    try:
        with urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=3) as r:
            data = json.loads(r.read().decode("utf-8"))
        return [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        return []


def extract(provider: str, text: str, model: str | None = None, timeout: int = 600):
    """Return the model's raw list of lead dicts, or [] when no model is used."""
    if provider in ("", "none"):
        return []
    if provider == "ollama":
        return _extract_ollama(text, model or DEFAULT_MODEL, timeout)
    raise ValueError(f"Unknown extraction provider '{provider}'.")


def _extract_ollama(text: str, model: str, timeout: int):
    if not ollama_available():
        raise ProviderUnavailable(
            f"No Ollama server at {OLLAMA_HOST}. Start it with `ollama serve`, "
            f"or choose the 'none' provider to use the channel map alone."
        )

    payload = {
        "model": model,
        "stream": False,
        "format": LEADS_SCHEMA,
        "options": {
            # Extraction is a copying task; sampling only invents variation.
            "temperature": 0,
            "num_ctx": 16384,
        },
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Implant document:\n\n{text}"},
        ],
    }
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise ProviderUnavailable(f"Ollama returned HTTP {e.code}: {detail}") from e
    except Exception as e:  # timeout, connection reset, etc.
        raise ProviderUnavailable(f"Ollama request failed: {e}") from e

    content = (body.get("message") or {}).get("content", "")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        # Should be impossible with a schema-constrained response, but a wrong
        # answer is recoverable and a crash is not.
        return []
    return parsed.get("leads", []) if isinstance(parsed, dict) else []
