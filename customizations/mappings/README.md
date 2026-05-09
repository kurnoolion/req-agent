# `customizations/mappings/` — bootstrap mapping snapshots

This directory holds **per-bootstrap mapping snapshots** that resolve
placeholders in profile JSONs to their real MNO / plan / release values
at parse time. Without these snapshots (or a fallback to
`<env_dir>/state/cline-mapping.json`), the parser sees regex strings
like `<MNO0>_REQ_<PLAN>_\d+` and matches nothing.

**Owned by Cline.** The on-prem AI assistant writes one file per
bootstrap run, named `<bootstrap_id>.json` (matching the placeholdered
profile in `customizations/profiles/<bootstrap_id>.json`). See
`cline-playbooks/bootstrap.md` for the write step and
`cline-playbooks/mapping.md` for the on-disk shape.

## Why this directory is gitignored

Mapping files contain real proprietary names (MNO short / alias / full
name, plan IDs, release codes) that **must never reach the public
GitHub mirror**. The repo's `.gitignore` blocks every file in this
directory except `.gitkeep` and this README. The work-PC pre-push hook
(installed by `~/work/utils/git-sync/sync-work.sh`) further blocks any
push to `github.com` from a machine where the mappings are present.

## How runtime substitution finds the mapping

`core.src.profiler.profile_substitute.load_substituted_profile()`
searches in this order:

1. `customizations/mappings/<profile_stem>.json` (this dir) — frozen
   per-bootstrap snapshot.
2. `<env_dir>/state/cline-mapping.json` — Cline's live mapping; always
   present on a work PC, grows over time as new MNOs / plans are
   onboarded.
3. None found → substitution is a no-op (profile used as-is). Public
   profiles like `vzw_oa_profile.json` rely on this path; their regex
   strings already carry real values.

## Sharing across team members

This dir is gitignored, so two work-PC developers don't share files
through git directly. Three options to share / reproduce mappings:

1. **Re-derive each PC** — Cline regenerates the mapping snapshot on
   first bootstrap from `<env_dir>/state/cline-mapping.json`. The
   redaction protocol is deterministic, so two developers running
   bootstrap on the same corpus get identical mappings. This is the
   default flow and needs no infrastructure.
2. **Encrypted file sync** — Box / OneDrive / corporate share for the
   directory contents. Symlink each developer's `customizations/
   mappings/` to the share.
3. **Separate internal-only repo** — host a private repo containing
   just the mapping snapshots; clone alongside this repo and symlink
   in. Suitable for larger teams with formal mapping governance.

Option 1 is the recommended default; the others are layered on as the
team's needs demand.

## Mapping file shape

```json
{
  "version": 1,
  "bootstrap_id": "bs_a3f2b1c4",
  "mappings": {
    "MNO0":        "VZ",
    "MNO0_ALIAS":  "VZW",
    "MNO0_NAME":   "Verizon",
    "PLAN0":       "<plan-id>",
    "PLAN1":       "<plan-id>",
    "REL0":        "<release-code>"
  }
}
```

Top-level `mappings` keys are placeholder names *without* angle
brackets (e.g. `MNO0`, not `<MNO0>`). The substitution layer adds the
brackets when matching against profile strings.

Cline's live mapping at `<env_dir>/state/cline-mapping.json` uses the
inverted shape (`{"<real>": "<placeholder>"}` for forward redaction) —
the substitution loader detects and normalizes both shapes.
