"""Turn an implant document into plain text, one entry per page.

The lab receives these in whatever form the surgical team produced: a text PDF,
a PDF of photographed handwriting, a PowerPoint, or a mix of all three in one
file. We read what we can and say plainly which pages we could not read, rather
than silently returning less text than the document actually contains — a
half-read document that looks fully read is the worst outcome here, because the
lead list would come back short with no indication anything was missed.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

# A page with a handful of stray characters (a slide number, a stamp) is still
# effectively an image as far as extraction goes.
_MIN_CHARS_FOR_TEXT_PAGE = 40


@dataclass
class Page:
    number: int  # 1-based, as a human would cite it
    text: str
    has_text_layer: bool

    @property
    def is_scanned(self) -> bool:
        return not self.has_text_layer


@dataclass
class Document:
    path: str
    kind: str  # "pdf" | "pptx"
    pages: list[Page] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(p.text for p in self.pages if p.text.strip())

    @property
    def scanned_pages(self) -> list[int]:
        return [p.number for p in self.pages if p.is_scanned]

    def summary(self) -> dict:
        return {
            "kind": self.kind,
            "pages": len(self.pages),
            "readable_pages": sum(1 for p in self.pages if p.has_text_layer),
            "scanned_pages": self.scanned_pages,
            "characters": len(self.text),
        }


def load(path: str) -> Document:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return _load_pdf(path)
    if ext in (".pptx", ".ppt"):
        return _load_pptx(path)
    raise ValueError(f"Unsupported document type '{ext}'. Expected .pdf or .pptx.")


def _load_pdf(path: str) -> Document:
    import pymupdf  # imported lazily so the scan endpoints work without it

    doc = Document(path=path, kind="pdf")
    with pymupdf.open(path) as pdf:
        for i, page in enumerate(pdf, start=1):
            text = page.get_text("text") or ""
            doc.pages.append(
                Page(
                    number=i,
                    text=text,
                    has_text_layer=len(text.strip()) >= _MIN_CHARS_FOR_TEXT_PAGE,
                )
            )
    return doc


def _load_pptx(path: str) -> Document:
    from pptx import Presentation

    doc = Document(path=path, kind="pptx")
    prs = Presentation(path)
    for i, slide in enumerate(prs.slides, start=1):
        chunks: list[str] = []
        for shape in slide.shapes:
            # Tables carry the lead list often enough to be worth walking
            # explicitly; shape.has_text_frame misses them.
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    chunks.append("\t".join(c.text for c in row.cells))
            elif getattr(shape, "has_text_frame", False):
                chunks.append(shape.text_frame.text)
        text = "\n".join(c for c in chunks if c.strip())
        doc.pages.append(
            Page(
                number=i,
                text=text,
                has_text_layer=len(text.strip()) >= _MIN_CHARS_FOR_TEXT_PAGE,
            )
        )
    return doc
