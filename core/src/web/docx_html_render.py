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
    # Whole-block strike (every textful run struck) → docx-struck on the
    # outer element. For partial strike, only the struck spans get
    # docx-struck via inline <span>s — see _render_paragraph_inner.
    if struck and _all_runs_struck(para):
        classes.append("docx-struck")
    cls = " ".join(classes)
    tag = f"h{min(level, 6)}" if level is not None else "p"
    return f'<{tag} class="{cls}" data-block-idx="{idx}">{_render_paragraph_inner(para, text)}</{tag}>'


def _render_paragraph_inner(para: DocxParagraph, fallback_text: str) -> str:
    """Render run-level HTML preserving per-run strike spans [D-060]."""
    parts: list[str] = []
    saw_any = False
    for run in para.runs:
        t = run.text or ""
        if not t:
            continue
        saw_any = True
        font = run.font
        struck = bool(
            getattr(font, "strike", None) or getattr(font, "double_strike", None)
        )
        escaped = escape(t)
        if struck:
            parts.append(f'<span class="docx-struck">{escaped}</span>')
        else:
            parts.append(escaped)
    if not saw_any:
        return escape(fallback_text)
    return "".join(parts)


def _all_runs_struck(para: DocxParagraph) -> bool:
    saw = False
    for run in para.runs:
        if not run.text or not run.text.strip():
            continue
        saw = True
        font = run.font
        if not (getattr(font, "strike", None) or getattr(font, "double_strike", None)):
            return False
    return saw


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
    """Render a docx table as HTML, preserving per-cell run-level strikes [D-060].

    Each cell becomes a sequence of <span class="docx-struck"> for struck
    runs and bare text for unstruck runs. Whole-row strike (every textful
    cell fully struck) puts ``docx-struck`` on the ``<tr>``; whole-table
    strike puts it on the ``<table>``.
    """
    # Build per-cell rendered HTML and per-cell struck flags.
    rendered_cells: list[list[str]] = []
    cell_struck: list[list[bool]] = []
    for row in tbl.rows:
        cell_html: list[str] = []
        cell_flags: list[bool] = []
        for c in row.cells:
            html, struck = _render_cell_runs(c)
            cell_html.append(html)
            cell_flags.append(struck)
        rendered_cells.append(cell_html)
        cell_struck.append(cell_flags)

    if not rendered_cells:
        return None

    header_html = rendered_cells[0]
    header_flags = cell_struck[0]
    body_html = rendered_cells[1:]
    body_flags = cell_struck[1:]

    # Match the extractor's degenerate-table skip: single empty column.
    headers_text = [(c.text or "").strip() for c in tbl.rows[0].cells]
    body_text = [
        [(c.text or "").strip() for c in r.cells] for r in tbl.rows[1:]
    ]
    non_empty_headers = [h for h in headers_text if h]
    total_cells = sum(1 for row in body_text for c in row if c)
    if len(non_empty_headers) <= 1 and total_cells == 0:
        return None

    # Whole-table struck: header row + every body row fully struck.
    header_all_struck = bool(header_flags) and all(
        s for s, t in zip(header_flags, headers_text) if t
    )
    body_all_struck = bool(body_flags) and all(
        all(s for s, t in zip(row_flags, row_text) if t)
        for row_flags, row_text in zip(body_flags, body_text)
    )
    table_struck = header_all_struck and body_all_struck

    cls_table = "docx-block docx-table" + (" docx-struck" if table_struck else "")
    parts = [f'<table class="{cls_table}" data-block-idx="{idx}">']
    if any(headers_text):
        parts.append("<thead><tr>")
        for cell_inner in header_html:
            parts.append(f"<th>{cell_inner}</th>")
        parts.append("</tr></thead>")
    parts.append("<tbody>")
    for row_idx, (row_inner, row_flags, row_text) in enumerate(
        zip(body_html, body_flags, body_text)
    ):
        row_all_struck = bool(row_text) and all(
            s for s, t in zip(row_flags, row_text) if t
        )
        cls_row = "docx-struck" if row_all_struck else ""
        parts.append(
            f'<tr data-row-idx="{row_idx}"'
            + (f' class="{cls_row}"' if cls_row else "")
            + ">"
        )
        for cell_inner in row_inner:
            parts.append(f"<td>{cell_inner}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def _render_cell_runs(cell) -> tuple[str, bool]:
    """Render a single cell's runs as HTML; return (html, all_textful_struck).

    A cell with no textful runs returns ("", False) — it can't be "struck".
    """
    parts: list[str] = []
    saw_textful = False
    all_struck = True
    for para in cell.paragraphs:
        for run in para.runs:
            t = run.text or ""
            if not t:
                continue
            font = run.font
            struck = bool(
                getattr(font, "strike", None) or getattr(font, "double_strike", None)
            )
            if t.strip():
                saw_textful = True
                if not struck:
                    all_struck = False
            escaped = escape(t)
            parts.append(
                f'<span class="docx-struck">{escaped}</span>' if struck else escaped
            )
    return "".join(parts), saw_textful and all_struck


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
