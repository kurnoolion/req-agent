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

## Trust boundary — pre-push hook, NOT gitignore [D-062]

This directory is **NOT gitignored**. The contents are committed,
pushed to the company-internal git remote, and shared across team
members through the normal git flow — that's the entire point: one
source of truth for the team's mappings, identical across every work
PC.

The trust boundary that keeps mapping files off the **public** mirror
(github.com) is the **pre-push hook** installed by
`~/work/utils/git-sync/sync-work.sh`:

- The hook rejects any `git push` whose remote URL contains
  `github.com`.
- Override: `NORA_ALLOW_PUBLIC_PUSH=1 git push origin main` —
  intentional, audited, used only for verified-clean force-pushes
  (e.g., a history rewrite that scrubs an earlier leak).
- The hook installs idempotently on every `sync-work.sh` run, so a
  missing/altered hook self-heals.

If you're working on a personal PC that doesn't run `sync-work.sh`,
**do not put mapping files in this directory**. The hook isn't there
to protect you, and `git push origin` would push them to the public
mirror.

## How runtime substitution finds the mapping

`core.src.profiler.profile_substitute.load_substituted_profile()`
searches in this order:

1. `customizations/mappings/<profile_stem>.json` (this dir) —
   per-bootstrap snapshot.
2. `<env_dir>/state/cline-mapping.json` — Cline's live mapping; always
   present on a work PC, grows over time as new MNOs / plans / releases
   are onboarded.
3. None found → substitution is a no-op (profile used as-is). Public
   profiles like `vzw_oa_profile.json` rely on this path; their regex
   strings already carry real values.

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
