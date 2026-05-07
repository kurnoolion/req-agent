"""Tests for the web markdown renderer.

`render_markdown` converts an LLM answer's markdown into Jinja-safe
HTML. Covers:
  - the formatting features the FACT / SUMMARIZE prompts emit
    (headers, bullets, **bold**, *italic*, fenced code, tables)
  - dangerous-tag stripping (raw HTML in LLM output is suspect)
  - empty / None robustness
  - citation tokens pass through as plain text
"""

from __future__ import annotations

from markupsafe import Markup

from core.src.web.markdown_render import render_markdown


# ── Robustness ─────────────────────────────────────────────────


class TestEmpty:
    def test_empty_string_returns_empty_markup(self):
        assert render_markdown("") == Markup("")

    def test_none_returns_empty_markup(self):
        assert render_markdown(None) == Markup("")


# ── Markdown features the FACT / SUMMARIZE prompts emit ─────────


class TestHeaders:
    def test_h2_renders(self):
        out = render_markdown("## TL;DR")
        assert "<h2>TL;DR</h2>" in out

    def test_bold_only_line_renders_as_strong(self):
        # SUMMARIZE prompt emits "**TL;DR**" on its own line
        out = render_markdown("**TL;DR**")
        assert "<strong>TL;DR</strong>" in out


class TestEmphasis:
    def test_bold_inline(self):
        out = render_markdown("The **T3402** timer is 720s.")
        assert "<strong>T3402</strong>" in out

    def test_italic_inline(self):
        out = render_markdown("The *attach* procedure starts.")
        assert "<em>attach</em>" in out


class TestLists:
    def test_bullet_list(self):
        out = render_markdown("- First\n- Second\n- Third")
        assert "<ul>" in out
        assert "<li>First</li>" in out
        assert "<li>Second</li>" in out

    def test_numbered_list(self):
        out = render_markdown("1. Step one\n2. Step two")
        assert "<ol>" in out
        assert "<li>Step one</li>" in out


class TestCode:
    def test_inline_code(self):
        out = render_markdown("Use `T3402` to retry.")
        assert "<code>T3402</code>" in out

    def test_fenced_code_block(self):
        src = "```\nVZ_REQ_X\nVZ_REQ_Y\n```"
        out = render_markdown(src)
        assert "<code>" in out
        assert "VZ_REQ_X" in out


class TestTables:
    def test_pipe_table_renders(self):
        src = (
            "| MNO | Timer |\n"
            "|---|---|\n"
            "| VZW | 720s |\n"
            "| TMO | 540s |"
        )
        out = render_markdown(src)
        assert "<table>" in out
        assert "<thead>" in out
        assert "<td>VZW</td>" in out


# ── Citation tokens pass through ───────────────────────────────


class TestCitationsPassThrough:
    def test_req_id_in_output(self):
        out = render_markdown(
            "The UE shall start T3402 (VZ_REQ_LTEDATARETRY_7748)."
        )
        assert "VZ_REQ_LTEDATARETRY_7748" in out

    def test_3gpp_spec_passes_through(self):
        out = render_markdown(
            "Per 3GPP TS 24.301, Section 5.5.1.2.6, the UE shall foo."
        )
        assert "3GPP TS 24.301" in out
        assert "Section 5.5.1.2.6" in out


# ── Realistic LLM output ───────────────────────────────────────


class TestRealisticAnswers:
    def test_summarize_style_output(self):
        src = (
            "**TL;DR**\n\n"
            "Authentication is governed by three requirements across "
            "the OTADM and AT-commands plans.\n\n"
            "**Per-section breakdown:**\n\n"
            "- Mutual auth at DM layer (VZ_REQ_LTEOTADM_7707).\n"
            "- Auth key generation (VZ_REQ_LTEOTADM_7666)."
        )
        out = render_markdown(src)
        assert "<strong>TL;DR</strong>" in out
        assert "<strong>Per-section breakdown:</strong>" in out
        assert "<ul>" in out
        assert "VZ_REQ_LTEOTADM_7707" in out

    def test_fact_style_output(self):
        # Note the blank line before the bullet list — required by
        # `sane_lists` extension. This is the format LLMs emit when
        # following standard markdown conventions; the prompt
        # examples in context_builder.py also follow this pattern.
        src = (
            "**Direct answer:** T3402 is 720 seconds (VZ_REQ_LTEDATARETRY_7748).\n\n"
            "**Supporting detail:**\n\n"
            "- The UE *shall* start T3402 upon receiving an Attach Reject "
            "with cause #7 (VZ_REQ_LTEDATARETRY_7748).\n"
            "- Per 3GPP TS 24.301, Section 5.5.1.2.6, the timer governs "
            "the wait period between retry attempts."
        )
        out = render_markdown(src)
        assert "<strong>Direct answer:</strong>" in out
        assert "<em>shall</em>" in out
        assert "<ul>" in out


# ── Safety: dangerous tags stripped ────────────────────────────


class TestSafety:
    def test_script_tag_removed(self):
        src = "Hello <script>alert('xss')</script> world."
        out = render_markdown(src)
        assert "<script>" not in out
        assert "alert" not in out

    def test_iframe_removed(self):
        out = render_markdown("Hello <iframe src='x'></iframe> world.")
        assert "<iframe>" not in out
        assert "iframe" not in out.lower()

    def test_style_tag_removed(self):
        src = "Hello <style>body{display:none}</style> world."
        out = render_markdown(src)
        assert "<style>" not in out
        assert "display:none" not in out

    def test_self_closing_dangerous_tag_removed(self):
        out = render_markdown("Hello <embed src='x' /> world.")
        assert "<embed" not in out

    def test_svg_with_onclick_removed(self):
        src = "Hello <svg onclick='evil()'><rect /></svg> world."
        out = render_markdown(src)
        assert "<svg" not in out
        assert "onclick" not in out

    def test_safe_content_preserved(self):
        src = "Normal text with **bold** and a (VZ_REQ_X_1) citation."
        out = render_markdown(src)
        assert "<strong>bold</strong>" in out
        assert "VZ_REQ_X_1" in out
