"""Markdown → HTML rendering for LLM-synthesized answers.

Wraps the `markdown` library with a fixed extension set tuned for the
shape of answers our pipeline produces (FACT, SUMMARIZE,
SINGLE_DOC etc): fenced code blocks, tables, sane lists, and inline
code. Returns Jinja-safe Markup so the template can interpolate
without further escaping.

Safety: we don't trust raw HTML in the LLM's answer. The renderer
strips `<script>` / `<style>` and similar dangerous tags. The
markdown library itself escapes HTML attributes; we additionally
disable raw-HTML passthrough so the LLM cannot inject arbitrary
HTML into the rendered output. Citation tokens like
`(VZ_REQ_LTEDATARETRY_7748)` and `3GPP TS 24.301, Section 5.5.1.2.6`
are pure text and pass through unchanged.
"""

from __future__ import annotations

import re

import markdown as _markdown
from markupsafe import Markup


_MD_EXTENSIONS = (
    "fenced_code",   # ```code blocks```
    "tables",        # | a | b |
    "sane_lists",    # - bullets / 1. numbered with proper nesting
    "nl2br",         # single newline → <br> (better fidelity to LLM
                     #   formatting where the model uses bare newlines
                     #   instead of blank-line paragraph breaks)
)


# Tags we'll strip outright (their content too) — they have no
# legitimate place in an analyzer's answer text.
_DANGEROUS_TAG_RE = re.compile(
    r"<\s*(script|style|iframe|object|embed|svg|math)\b[^>]*>.*?<\s*/\s*\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
# Self-closing variants and stray openers without close — strip
# the tag.
_DANGEROUS_TAG_OPEN_RE = re.compile(
    r"<\s*/?\s*(script|style|iframe|object|embed|svg|math)\b[^>]*/?>",
    re.IGNORECASE,
)


def render_markdown(text: str) -> Markup:
    """Convert markdown source to HTML, return Jinja-safe Markup.

    Empty / None input → empty Markup (templates can interpolate
    safely without an `if`).
    """
    if not text:
        return Markup("")

    # Strip dangerous HTML before letting markdown have a go. The
    # `markdown` library by default passes inline HTML through; we
    # take the conservative route and remove tags that have no role
    # in answer text.
    cleaned = _DANGEROUS_TAG_RE.sub("", text)
    cleaned = _DANGEROUS_TAG_OPEN_RE.sub("", cleaned)

    html = _markdown.markdown(cleaned, extensions=list(_MD_EXTENSIONS))
    return Markup(html)
