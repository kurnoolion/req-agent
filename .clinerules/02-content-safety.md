# Content safety: nothing proprietary leaves the on-prem machine

The user reads your reports off your screen and hand-types into Teacher LLM. Teacher LLM must NEVER
see verbatim corpus content, MNO names, plan IDs, requirement IDs, release codes, or any
file path under `<env_dir>/input/`.

## Redaction protocol

You maintain a literal-string mapping at `<env_dir>/state/cline-mapping.json`. Apply it
forward (real → placeholder) before emitting any report, and reverse (placeholder → real)
when acting on Teacher LLM's response.

**Mapping schema**:

```json
{
  "version": 1,
  "mappings": {
    "<real-string>": "<placeholder>"
  }
}
```

**Placeholder format** — angle-bracketed, category-prefixed, stable index:

| Category | Pattern | Example |
|---|---|---|
| MNO short prefix | `<MNO{N}>` | `VZ` → `<MNO0>` |
| MNO alias | `<MNO{N}_ALIAS>` | `VZW` → `<MNO0_ALIAS>` |
| MNO full name | `<MNO{N}_NAME>` | `Verizon` → `<MNO0_NAME>` |
| Plan ID | `<PLAN{N}>` | `LTEAT` → `<PLAN0>` |
| Plan name | `<PLAN{N}_NAME>` | (use when plan_name differs from plan_id) |
| Release | `<REL{N}>` | `OA-baseline` → `<REL0>` |
| Requirement ID | `<REQID-{N}>` | `VZ_REQ_LTEAT_45` → `<REQID-0>` |
| Standards spec | `<SPEC{N}>` | `3GPP TS 24.301` → keep as-is (public standard, not proprietary) |

`{N}` is a stable index — once allocated, never changes. New entries get the next free index.

Apply substitution **longest-match-first** so `VZ_REQ_LTEAT_45` matches before `VZ`.

The mapping playbook (`cline-playbooks/mapping.md`) describes how to seed and grow this
file.

## Hard rules — never include in your report

- Verbatim quotes from any document under `<env_dir>/input/`
- Section heading text > 5 words (treat as title-class quoted prose)
- Requirement body text (any length)
- Acronym definitions in full (the expansion phrase IS corpus content)
- Tabular requirement data
- Real values for any token in the mapping (always emit the placeholder)
- Un-redacted file paths under `<env_dir>/input/<...>` (the path components are MNO/RELEASE/PLAN)

## OK to include (after redaction)

- Counts, percentages, ratios
- Generic regex patterns — `^\d+(?:\.\d+)+\s+\S` is fine
- Format-class observations — `89% of headings are numbered N.N.N`
- Coverage stats — `rule catches 487/503`
- Counts of misses by severity — `HIGH=96%, MED=3%, LOW=0.1%`
- Source code paths inside the repo — `core/src/parser/structural_parser.py:1243`
  (those are repo paths, not corpus)
- Public standards references — `3GPP TS 24.301, Section 5.5.1.2.6` (public knowledge)
- Domain terminology — `ATTACH`, `EMM`, `NAS` (3GPP standard terms)

## Borderline cases

A regex that ORs corpus-specific values is suspect: `(ATTACH|DETACH|FOO)` is fine if all
three are public 3GPP terms; not fine if `FOO` is a customer-specific keyword. When unsure,
add `FOO` to the mapping and emit the redacted form.

When unsure in general: ask the user. Default to redaction.

## What this protects against

A passing observer of the user's hand-typed reports — and Teacher LLM itself, which logs
conversations — never sees any string that uniquely identifies a customer, document,
release, or specific requirement. Patterns and counts are sufficient for Teacher LLM to
update code; concrete values stay on-prem.

## Mapping snapshot location [D-062]

Beyond the live `<env_dir>/state/cline-mapping.json` (forward redaction for outgoing
reports), Cline also maintains a **per-bootstrap mapping snapshot** at:

```
customizations/mappings/<bootstrap_id>.json
```

This snapshot pairs with the placeholdered profile at
`customizations/profiles/<bootstrap_id>.json` (which Teacher LLM commits to public
github). At parse time, NORA's runtime substitution layer reads the snapshot and
resolves placeholders in the profile's regex strings to real values.

**The `customizations/mappings/` directory is NOT gitignored**. The contents are
committed and pushed to the **company-internal** git remote so every team member
shares one source of truth for the mappings. The trust boundary against the **public**
mirror (`github.com`) is the work-PC pre-push hook installed by
`~/work/utils/git-sync/sync-work.sh`: any `git push` whose remote URL is `github.com`
is rejected unless `NORA_ALLOW_PUBLIC_PUSH=1` is set explicitly (used only for
audited force-pushes such as history rewrites).

You own this directory. `cline-playbooks/bootstrap.md` Step 8 specifies the write
operation; `cline-playbooks/mapping.md` documents the on-disk shape and the live-vs-
snapshot distinction. The directory IS suitable for git tracking — staging and
committing mapping files is part of the normal team-sync flow. The hook (not
`.gitignore`) is what keeps them off the public mirror.
