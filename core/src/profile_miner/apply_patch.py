"""Apply a ``ProfilePatch`` (output of ``mine_patterns``) to the
per-env corrections profile.

Public surface:
- ``merge_regex(existing, new) -> str`` — alternation-merge with
  inline-flag dedup.
- ``apply_patch(patch_data, profile_data) -> ApplyReport`` — pure
  function (no I/O); takes raw JSON dicts and returns an updated
  dict + report of changes. Easy to unit-test.
- ``apply_patch_files(env_dir, doc_id=None, dry_run=False) -> ApplyReport``
  — the CLI's working horse: scans ``<env_dir>/reports/profile_patch_*.json``,
  loads / seeds ``<env_dir>/corrections/profile.json``, merges, writes.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Regex merge with inline-flag dedup
# ---------------------------------------------------------------------------

def _strip_leading_iflag(pat: str) -> tuple[bool, str]:
    """``(?i)foo`` → ``(True, "foo")``; ``foo`` → ``(False, "foo")``.
    Only the simple leading-``(?i)`` form is recognised — embedded /
    grouped flag-toggles (``(?i:foo)``) are left untouched."""
    if pat.startswith("(?i)"):
        return True, pat[4:]
    return False, pat


def merge_regex(existing: str, new: str) -> str:
    """Combine two regex strings via alternation, deduplicating a
    shared leading ``(?i)`` inline flag so the result is valid under
    Python 3.11+ (which warns when inline flags appear mid-pattern).

    - empty / whitespace ``existing`` → ``new`` (replacement, not merge).
    - identical strings → unchanged.
    - else: ``(?i)(?:<a>|<b>)`` if either had the flag; else ``(?:<a>|<b>)``.
    """
    if not existing or not existing.strip():
        return new
    if existing == new:
        return existing

    flag_a, body_a = _strip_leading_iflag(existing)
    flag_b, body_b = _strip_leading_iflag(new)
    flag = "(?i)" if (flag_a or flag_b) else ""
    return f"{flag}(?:{body_a}|{body_b})"


# ---------------------------------------------------------------------------
# Dotted-path get/set on the profile JSON
# ---------------------------------------------------------------------------

def _get_dotted(d: Any, path: str) -> Any:
    cur = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _set_dotted(d: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    cur = d
    for p in parts[:-1]:
        if p not in cur or not isinstance(cur[p], dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value


# ---------------------------------------------------------------------------
# Apply report
# ---------------------------------------------------------------------------

@dataclass
class FieldChange:
    profile_field: str
    action: str  # "set" | "merged" | "appended" | "skipped:already-present" | "skipped:unmapped"
    old_value: Any = None
    new_value: Any = None
    source_doc: str = ""


@dataclass
class ApplyReport:
    changes: list[FieldChange] = field(default_factory=list)
    skipped_unmapped: list[str] = field(default_factory=list)
    """Names of unmapped fields encountered (the patch's ``unmapped``
    bucket). Surfaced so the reviewer can place these manually."""

    @property
    def modified(self) -> bool:
        return any(
            c.action in ("set", "merged", "appended") for c in self.changes
        )


# ---------------------------------------------------------------------------
# Core merge: patch dict → profile dict
# ---------------------------------------------------------------------------

def apply_patch(patch_data: dict, profile_data: dict,
                source_doc: str = "") -> ApplyReport:
    """Apply one patch (already-loaded JSON dict) on top of one profile
    (already-loaded JSON dict, modified IN PLACE).

    Pure function — no I/O. Returns a report of every field touched.
    Skips entries in ``patch_data['unmapped']`` (the reviewer must place
    those manually) but records them in ``report.skipped_unmapped``.
    """
    report = ApplyReport()

    for entry in patch_data.get("field_patches", []) or []:
        field_path = entry.get("profile_field", "")
        proposed = (entry.get("proposed_pattern") or "").strip()
        is_list = bool(entry.get("list_field", False))
        if not field_path or not proposed:
            continue

        current = _get_dotted(profile_data, field_path)

        if is_list:
            existing_list = list(current) if isinstance(current, list) else []
            if proposed in existing_list:
                report.changes.append(FieldChange(
                    profile_field=field_path,
                    action="skipped:already-present",
                    old_value=existing_list,
                    new_value=existing_list,
                    source_doc=source_doc,
                ))
                continue
            new_list = existing_list + [proposed]
            _set_dotted(profile_data, field_path, new_list)
            report.changes.append(FieldChange(
                profile_field=field_path,
                action="appended",
                old_value=existing_list,
                new_value=new_list,
                source_doc=source_doc,
            ))
            continue

        # Scalar string field
        existing = current if isinstance(current, str) else ""
        if not existing.strip():
            _set_dotted(profile_data, field_path, proposed)
            report.changes.append(FieldChange(
                profile_field=field_path,
                action="set",
                old_value=existing,
                new_value=proposed,
                source_doc=source_doc,
            ))
            continue

        if existing == proposed:
            report.changes.append(FieldChange(
                profile_field=field_path,
                action="skipped:already-present",
                old_value=existing,
                new_value=existing,
                source_doc=source_doc,
            ))
            continue

        merged = merge_regex(existing, proposed)
        _set_dotted(profile_data, field_path, merged)
        report.changes.append(FieldChange(
            profile_field=field_path,
            action="merged",
            old_value=existing,
            new_value=merged,
            source_doc=source_doc,
        ))

    for entry in patch_data.get("unmapped", []) or []:
        report.skipped_unmapped.append(entry.get("profile_field", ""))

    return report


# ---------------------------------------------------------------------------
# File-level orchestrator (used by the CLI)
# ---------------------------------------------------------------------------

def _iter_patch_files(env_dir: Path, doc_id: str | None) -> list[Path]:
    reports_dir = env_dir / "reports"
    if not reports_dir.is_dir():
        return []
    if doc_id:
        p = reports_dir / f"profile_patch_{doc_id}.json"
        return [p] if p.exists() else []
    return sorted(reports_dir.glob("profile_patch_*.json"))


def _seed_corrections_profile(env_dir: Path) -> Path | None:
    """Copy ``<env_dir>/out/profile/*.json`` to
    ``<env_dir>/corrections/profile.json`` when the latter is absent.
    Returns the path written, or None if no source profile exists."""
    out_dir = env_dir / "out" / "profile"
    if not out_dir.is_dir():
        return None
    candidates = sorted(out_dir.glob("*.json"))
    if not candidates:
        return None
    dst = env_dir / "corrections" / "profile.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(candidates[0], dst)
    return dst


def apply_patch_files(
    env_dir: Path,
    doc_id: str | None = None,
    dry_run: bool = False,
) -> tuple[ApplyReport, Path | None]:
    """Walk every ``profile_patch_<doc>.json`` under
    ``<env_dir>/reports/``, merge them into
    ``<env_dir>/corrections/profile.json`` (seeded from
    ``<env_dir>/out/profile/*.json`` when absent), and write back unless
    ``dry_run``. Returns ``(combined_report, corrections_path or None)``.
    """
    patch_paths = _iter_patch_files(env_dir, doc_id)
    if not patch_paths:
        return ApplyReport(), None

    corrections_path = env_dir / "corrections" / "profile.json"
    if not corrections_path.exists():
        seeded = _seed_corrections_profile(env_dir)
        if seeded is None:
            raise FileNotFoundError(
                "No <env_dir>/corrections/profile.json and no "
                "<env_dir>/out/profile/*.json to seed from. Run the "
                "profile stage of the pipeline first."
            )
        logger.info("Seeded corrections profile from %s", seeded)

    profile_data = json.loads(corrections_path.read_text(encoding="utf-8"))

    combined = ApplyReport()
    for patch_path in patch_paths:
        patch_data = json.loads(patch_path.read_text(encoding="utf-8"))
        src_doc = patch_data.get("doc_id", patch_path.stem)
        report = apply_patch(patch_data, profile_data, source_doc=src_doc)
        combined.changes.extend(report.changes)
        combined.skipped_unmapped.extend(report.skipped_unmapped)

    if combined.modified and not dry_run:
        corrections_path.write_text(
            json.dumps(profile_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    return combined, corrections_path
