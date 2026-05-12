"""Redact proprietary tokens before sending text to the LLM and restore
canonical placeholders on the way back.

Three classes of token, indexed in first-seen order so the LLM can
distinguish multiple operators / plans inside a single prompt:

- ``<MNO0>``, ``<MNO1>`` … — operator names (verizon, att, t-mobile, …)
- ``<PLAN0>``, ``<PLAN1>`` … — plan / release identifiers
- ``<MNO0>_REQ_<PLAN0>_\\d+`` — composed req-id token (preserved as a
  single unit; we don't want the LLM proposing a regex over a partially
  redacted req-id).

The same ``Redactor`` instance handles redact + restore so the indexing
is consistent across calls within one mining run.
"""

from __future__ import annotations

import re


# Known MNO surface forms (case-insensitive). Order matters only for
# stable indexing within a single run, not for correctness.
_MNO_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("verizon",  re.compile(r"\bverizon\b",                  re.IGNORECASE)),
    ("vzw",      re.compile(r"\bvzw\b",                      re.IGNORECASE)),
    ("vz",       re.compile(r"\bvz\b",                       re.IGNORECASE)),
    ("att",      re.compile(r"\bat\s*&\s*t\b|\bat&t\b",      re.IGNORECASE)),
    ("att2",     re.compile(r"\batt\b",                      re.IGNORECASE)),
    ("tmobile",  re.compile(r"\bt[\s-]?mobile\b",            re.IGNORECASE)),
    ("tmo",      re.compile(r"\btmo\b",                      re.IGNORECASE)),
]


class Redactor:
    """Stateful redactor: assigns deterministic ``<MNO0>``, ``<PLAN0>``,
    … placeholders on first sight of each unique token and reuses them
    on subsequent sightings within the same instance."""

    def __init__(self) -> None:
        self._mno_map: dict[str, str] = {}   # lower-cased surface → <MNO\d+>
        self._plan_map: dict[str, str] = {}  # surface → <PLAN\d+>

    # -- redaction --------------------------------------------------------

    def redact(self, text: str) -> str:
        """Replace MNO names, plan IDs, and composed req-ids with
        canonical placeholders. Idempotent on already-redacted text."""
        out = text

        # 1. Composed req-ids first so the inner MNO/PLAN tokens are
        #    preserved as a unit. Pattern: <PREFIX>_REQ_<PLANID>_<digits>
        #    where PREFIX is an MNO surface (VZ_REQ, ATT_REQ, TMO_REQ).
        out = self._redact_req_ids(out)

        # 2. MNO surface forms.
        for canonical, pat in _MNO_PATTERNS:
            out = pat.sub(lambda _m, c=canonical: self._mno_token(c), out)

        # 3. Plan IDs (uppercase tokens 4-20 chars long, no embedded
        #    space). We look for them next to ``Plan Id:`` / ``Plan
        #    Name:`` markers to avoid sweeping up unrelated UPPERCASE
        #    body words.
        out = self._redact_plan_ids(out)

        return out

    def _mno_token(self, canonical: str) -> str:
        if canonical not in self._mno_map:
            self._mno_map[canonical] = f"<MNO{len(self._mno_map)}>"
        return self._mno_map[canonical]

    def _plan_token(self, surface: str) -> str:
        if surface not in self._plan_map:
            self._plan_map[surface] = f"<PLAN{len(self._plan_map)}>"
        return self._plan_map[surface]

    def _redact_req_ids(self, text: str) -> str:
        # <PREFIX>_REQ_<PLAN>_<digits>. PREFIX is alphanumeric (2-6 chars);
        # PLAN is uppercase/underscore (2-30 chars); digits at the tail.
        pat = re.compile(
            r"\b([A-Z]{2,6})_REQ_([A-Z0-9_]{2,30})_(\d+)\b"
        )

        def repl(m: re.Match[str]) -> str:
            mno_tok = self._mno_token(m.group(1).lower())
            plan_tok = self._plan_token(m.group(2))
            return f"{mno_tok}_REQ_{plan_tok}_\\d+"

        return pat.sub(repl, text)

    def _redact_plan_ids(self, text: str) -> str:
        # ``Plan Id: <SURFACE>`` / ``Plan Name: <SURFACE>``
        pat = re.compile(
            r"(Plan\s+(?:Id|Name)\s*[:\-]\s*)([A-Z][A-Z0-9_]{1,29})",
            re.IGNORECASE,
        )

        def repl(m: re.Match[str]) -> str:
            return m.group(1) + self._plan_token(m.group(2))

        return pat.sub(repl, text)

    # -- restoration ------------------------------------------------------

    def restore_in_regex(self, regex: str) -> str:
        """LLM output is a regex over redacted text. We *don't* want to
        expand the placeholders back to literal surface forms — the
        whole point is that the patch is portable across MNOs/plans.

        This method instead canonicalises the placeholders so reviewers
        can read them: ``<MNO0>`` becomes the regex char class
        ``(?:VZ|ATT|TMO)`` (etc.) only when explicitly requested.

        For now we just leave the placeholders intact and let the
        reviewer decide. Returned unchanged."""
        return regex

    # -- introspection ----------------------------------------------------

    def mno_map(self) -> dict[str, str]:
        return dict(self._mno_map)

    def plan_map(self) -> dict[str, str]:
        return dict(self._plan_map)
