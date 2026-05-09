"""DOCX → HTML renderer aligned with DOCXExtractor's block indexing.

Produces an HTML fragment for the Bootstrap annotation harness. Walks the
docx body in the same order as :class:`DOCXExtractor.extract`, applying
the same skip rules so every emitted element carries a ``data-block-idx``
attribute that matches the IR's ``ContentBlock.position.index``.

Tables additionally emit ``data-row-idx`` on each body ``<tr>`` (header row
omitted from the IR's ``rows`` list, so it carries no row index). Empty
paragraphs and degenerate tables are skipped without consuming an index,
mirroring :meth:`DOCXExtractor._paragraph_block` / ``_table_block``.

Images are rendered as small placeholder elements; the harness only needs
positional alignment, not pixel fidelity.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from docx import Document as DocxDocument
from docx.oxml.ns import qn
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph


def render_docx_html(file_path: Path) -> str:
    """Render *file_path* as an HTML fragment with IR-aligned data attributes."""
    doc = DocxDocument(str(file_path))
    parts: list[str] = []
    block_idx = 0

    for child in doc.element.body.iterchildren():
        tag = child.tag
        if tag == qn("w:p"):
            para = DocxParagraph(child, doc)
            text = (para.text or "").strip()
            if not text:
                continue
            parts.append(_render_paragraph(para, text, block_idx))
            block_idx += 1
            # Inline images inside this paragraph each consume one index.
            image_count = _count_paragraph_images(doc, para)
            for _ in range(image_count):
                parts.append(
                    f'<div class="docx-image" data-block-idx="{block_idx}">'
                    f'<i class="bi bi-image"></i> [image]</div>'
                )
                block_idx += 1
        elif tag == qn("w:tbl"):
            tbl = DocxTable(child, doc)
            html = _render_table(tbl, block_idx)
            if html is None:
                continue  # degenerate table — extractor also drops it
            parts.append(html)
            block_idx += 1

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Paragraph rendering
# ---------------------------------------------------------------------------

_HEADING_STYLE_PREFIX = "heading"


def _render_paragraph(para: DocxParagraph, text: str, idx: int) -> str:
    style_name = (para.style.name or "") if para.style is not None else ""
    level = _heading_level(style_name)
    classes = ["docx-block"]
    if level is not None:
        classes.append(f"docx-h{min(level, 6)}")
    bold, italic, struck = _para_run_flags(para)
    if bold:
        classes.append("docx-bold")
    if italic:
        classes.append("docx-italic")
    if struck:
        classes.append("docx-struck")
    cls = " ".join(classes)
    tag = f"h{min(level, 6)}" if level is not None else "p"
    return f'<{tag} class="{cls}" data-block-idx="{idx}">{escape(text)}</{tag}>'


def _heading_level(style_name: str) -> int | None:
    s = style_name.strip().lower()
    if not s.startswith(_HEADING_STYLE_PREFIX):
        return None
    rest = s[len(_HEADING_STYLE_PREFIX):].strip()
    if rest.isdigit():
        try:
            n = int(rest)
        except ValueError:
            return None
        return n if 1 <= n <= 9 else None
    return None


def _para_run_flags(para: DocxParagraph) -> tuple[bool, bool, bool]:
    """Approximate (bold, italic, strikethrough) flags from runs.

    Mirrors :meth:`DOCXExtractor._paragraph_font` semantics enough to give
    the user a consistent visual cue. We do **not** synthesize a font size
    here — that's only needed by the profiler.
    """
    bold = False
    italic = False
    struck = False
    for run in para.runs:
        if not run.text or not run.text.strip():
            continue
        if run.bold:
            bold = True
        if run.italic:
            italic = True
        font = run.font
        if getattr(font, "strike", None) or getattr(font, "double_strike", None):
            struck = True
        if bold and italic and struck:
            break
    return bold, italic, struck


# ---------------------------------------------------------------------------
# Table rendering
# ---------------------------------------------------------------------------

def _render_table(tbl: DocxTable, idx: int) -> str | None:
    rows_text: list[list[str]] = []
    for row in tbl.rows:
        cells = [(c.text or "").strip() for c in row.cells]
        rows_text.append(cells)
    if not rows_text:
        return None

    headers = rows_text[0]
    body_rows = rows_text[1:]

    non_empty_headers = [h for h in headers if h]
    total_cells = sum(1 for row in body_rows for c in row if c)
    if len(non_empty_headers) <= 1 and total_cells == 0:
        return None  # extractor drops this; we do too

    parts = [f'<table class="docx-block docx-table" data-block-idx="{idx}">']
    if any(headers):
        parts.append("<thead><tr>")
        for h in headers:
            parts.append(f"<th>{escape(h)}</th>")
        parts.append("</tr></thead>")
    parts.append("<tbody>")
    for row_idx, row in enumerate(body_rows):
        parts.append(f'<tr data-row-idx="{row_idx}">')
        for cell in row:
            parts.append(f"<td>{escape(cell)}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Image counting (for index alignment only — we don't render image bytes)
# ---------------------------------------------------------------------------

def _count_paragraph_images(doc, para: DocxParagraph) -> int:
    """Count inline images inside *para* that the extractor would emit.

    Mirrors :meth:`DOCXExtractor._extract_paragraph_images` so emitted
    placeholder ``data-block-idx`` values stay aligned with the IR.
    """
    blip_tag = qn("a:blip")
    embed_attr = qn("r:embed")
    count = 0
    for blip in para._element.iter(blip_tag):
        rel_id = blip.get(embed_attr)
        if not rel_id:
            continue
        rel = doc.part.rels.get(rel_id)
        if rel is None or "image" not in rel.reltype:
            continue
        count += 1
    return count
