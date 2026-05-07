"""Tests for Stage 6.5 — per-sentence citation audit.

`audit_answer_citations` walks the LLM's answer sentence-by-sentence,
flagging:
  - sentences without any inline citation (uncited claims)
  - citations that look real but reference req IDs not in the
    available context (fabricated)
  - markdown headers / TL;DR labels / bare section titles (meta —
    excluded from the cited-percentage metric)
"""

from __future__ import annotations

from core.src.query.citation_audit import (
    _is_markdown_header,
    _split_sentences,
    audit_answer_citations,
)


# ── Sentence splitting ─────────────────────────────────────────


class TestSplitSentences:
    def test_empty_string_returns_empty(self):
        assert _split_sentences("") == []

    def test_single_sentence(self):
        assert _split_sentences("The UE shall start the timer.") == [
            "The UE shall start the timer."
        ]

    def test_two_sentences_split_on_period_space(self):
        out = _split_sentences("Sentence one. Sentence two.")
        assert out == ["Sentence one.", "Sentence two."]

    def test_abbreviation_does_not_split(self):
        out = _split_sentences("The timer (e.g. T3402) is 720 seconds.")
        assert out == ["The timer (e.g. T3402) is 720 seconds."]

    def test_paragraph_break_separates(self):
        out = _split_sentences("Paragraph one.\n\nParagraph two.")
        assert "Paragraph one." in out
        assert "Paragraph two." in out

    def test_bullet_items_each_become_sentence(self):
        text = "- First item with citation (REQ_1)\n- Second item"
        out = _split_sentences(text)
        assert len(out) == 2

    def test_numbered_list_items_become_sentences(self):
        text = "1. First step.\n2. Second step."
        out = _split_sentences(text)
        assert len(out) == 2

    def test_markdown_header_preserved_as_sentence(self):
        out = _split_sentences("**TL;DR**\n\nThe T3402 timer is 720 seconds.")
        assert any("TL;DR" in s for s in out)
        assert any("720 seconds" in s for s in out)


class TestMarkdownHeaderDetection:
    def test_hash_header(self):
        assert _is_markdown_header("# Header")
        assert _is_markdown_header("## Sub-header")

    def test_bold_only_line(self):
        assert _is_markdown_header("**TL;DR**")
        assert _is_markdown_header("**Per-section breakdown**")

    def test_bold_with_colon_treated_as_header(self):
        assert _is_markdown_header("**Note:**")

    def test_bold_with_inline_content_is_not_header(self):
        # "**Note**: foo bar" has body after the bold — factual sentence.
        assert not _is_markdown_header("**Note** foo bar.")

    def test_plain_sentence_not_header(self):
        assert not _is_markdown_header("The T3402 timer is 720 seconds.")


# ── Audit basics ───────────────────────────────────────────────


class TestAuditBasics:
    def test_empty_answer_zero_counts(self):
        a = audit_answer_citations("", [])
        assert a.factual_sentence_count == 0
        assert a.cited_sentence_count == 0
        assert a.cited_percent == 100.0  # vacuous

    def test_one_cited_sentence(self):
        ans = "The UE shall start T3402 (VZ_REQ_LTEDATARETRY_7748)."
        a = audit_answer_citations(ans, ["VZ_REQ_LTEDATARETRY_7748"])
        assert a.factual_sentence_count == 1
        assert a.cited_sentence_count == 1
        assert a.cited_percent == 100.0
        assert a.fabricated_count == 0

    def test_one_uncited_sentence(self):
        ans = "The UE shall start the timer."
        a = audit_answer_citations(ans, ["VZ_REQ_LTEDATARETRY_7748"])
        assert a.factual_sentence_count == 1
        assert a.cited_sentence_count == 0
        assert a.cited_percent == 0.0

    def test_mixed_cited_and_uncited(self):
        ans = (
            "The UE shall start T3402 (VZ_REQ_LTEDATARETRY_7748). "
            "Then the device waits."
        )
        a = audit_answer_citations(ans, ["VZ_REQ_LTEDATARETRY_7748"])
        assert a.factual_sentence_count == 2
        assert a.cited_sentence_count == 1
        assert a.cited_percent == 50.0


# ── Fabrication detection ──────────────────────────────────────


class TestFabricationDetection:
    def test_real_citation_not_fabricated(self):
        ans = "Per VZ_REQ_LTEDATARETRY_7748, T3402 is 720s."
        a = audit_answer_citations(ans, ["VZ_REQ_LTEDATARETRY_7748"])
        assert a.fabricated_count == 0

    def test_unknown_req_id_flagged(self):
        ans = "Per VZ_REQ_LTEDATARETRY_99999, the timer is 720s."
        a = audit_answer_citations(ans, ["VZ_REQ_LTEDATARETRY_7748"])
        assert a.fabricated_count == 1
        # The fabricated id surfaces in the per-sentence audit
        fab_sentences = [s for s in a.sentences if s.fabricated_citations]
        assert "VZ_REQ_LTEDATARETRY_99999" in fab_sentences[0].fabricated_citations

    def test_no_available_ids_disables_fabrication_check(self):
        """When available_req_ids is None or empty, fabrication is
        not checked — every citation passes."""
        ans = "Per VZ_REQ_LTEDATARETRY_99999, foo."
        a = audit_answer_citations(ans, [])
        assert a.fabricated_count == 0

    def test_3gpp_spec_citation_not_subject_to_fabrication_check(self):
        """3GPP TS citations are external; the audit only checks
        req_id fabrication. A spec citation always 'passes'."""
        ans = "Per 3GPP TS 24.301, Section 5.5.1.2.6, foo."
        a = audit_answer_citations(ans, ["VZ_REQ_X_1"])
        assert a.fabricated_count == 0


# ── Meta sentence handling ─────────────────────────────────────


class TestMetaSentences:
    def test_markdown_header_does_not_count(self):
        ans = "**TL;DR**\n\nThe T3402 timer (VZ_REQ_X_1) is 720s."
        a = audit_answer_citations(ans, ["VZ_REQ_X_1"])
        # Only the body sentence is factual; header is meta.
        assert a.factual_sentence_count == 1
        assert a.cited_sentence_count == 1
        assert a.cited_percent == 100.0

    def test_label_only_line_does_not_count(self):
        ans = "Direct answer:\n\nThe value is 720s (VZ_REQ_X_1)."
        a = audit_answer_citations(ans, ["VZ_REQ_X_1"])
        assert a.factual_sentence_count == 1


# ── Uncited sentences accessor ─────────────────────────────────


class TestUncitedAccessor:
    def test_uncited_sentences_lists_only_uncited(self):
        ans = (
            "Cited claim (VZ_REQ_X_1). "
            "Uncited claim. "
            "Another cited (VZ_REQ_X_2)."
        )
        a = audit_answer_citations(ans, ["VZ_REQ_X_1", "VZ_REQ_X_2"])
        u = a.uncited_sentences
        assert len(u) == 1
        assert "Uncited claim" in u[0].text

    def test_uncited_excludes_meta(self):
        ans = "**TL;DR**\n\nFoo bar baz."
        a = audit_answer_citations(ans, [])
        u = a.uncited_sentences
        # Header is meta — not in uncited list
        assert all("TL;DR" not in s.text for s in u)
        # Body sentence is factual + uncited
        assert any("Foo bar baz" in s.text for s in u)


# ── Realistic multi-sentence answers ───────────────────────────


class TestRealisticAnswers:
    def test_summarize_style_answer(self):
        """SUMMARIZE-style answer — header + bullet items."""
        ans = (
            "**TL;DR**\n\n"
            "Authentication is governed by three requirements.\n\n"
            "**Per-section breakdown:**\n\n"
            "- Mutual auth at DM layer (VZ_REQ_LTEOTADM_7707).\n"
            "- Auth key generation (VZ_REQ_LTEOTADM_7666).\n"
            "- Device shall support digest authentication."
        )
        available = ["VZ_REQ_LTEOTADM_7707", "VZ_REQ_LTEOTADM_7666"]
        a = audit_answer_citations(ans, available)
        # 4 factual sentences (1 intro + 3 bullets); 2 markdown headers
        assert a.factual_sentence_count == 4
        # 2 of the 3 bullets cite; the intro and one bullet don't
        assert a.cited_sentence_count == 2
        assert a.fabricated_count == 0

    def test_fact_style_answer_with_contradiction(self):
        ans = (
            "Per VZ_REQ_LTEDATARETRY_7748, T3402 is 720s. "
            "Per VZ_REQ_LTEOTADM_3300, T3402 is 540s. "
            "The values disagree across documents."
        )
        a = audit_answer_citations(
            ans, ["VZ_REQ_LTEDATARETRY_7748", "VZ_REQ_LTEOTADM_3300"],
        )
        assert a.factual_sentence_count == 3
        assert a.cited_sentence_count == 2
        assert a.fabricated_count == 0
