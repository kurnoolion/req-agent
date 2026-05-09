# Playbook: maintain the redaction mapping

**Purpose**: ensure proprietary tokens (MNO names, plan IDs, release codes, requirement
IDs, file paths) get replaced with stable placeholders in every report you produce.

**File location**: `<env_dir>/state/cline-mapping.json`. Never enters git (`<env_dir>` is
not in the repo).

## Schema

```json
{
  "version": 1,
  "mappings": {
    "<real-string>": "<placeholder>"
  }
}
```

## Placeholder allocation

Per `02-content-safety.md`. Each new entry:

1. Determine category (MNO short / MNO alias / MNO name / Plan ID / Plan name /
   Release / Req ID).
2. Find the highest existing index `{N}` in that category.
3. Allocate `{N+1}`.
4. Append `<real>: <placeholder>` to `mappings`.
5. Write the file back atomically (write to `.tmp`, rename).

## Forward redaction (for outgoing reports)

Walk all keys longest-first. Apply literal-string replacement to every report token before
emitting. Example transformations:

| Input | After redaction |
|---|---|
| `LTEAT` | `<PLAN0>` |
| `VZ_REQ_LTEAT_45` | `<REQID-0>` |
| `<env_dir>/input/VZW/OA-baseline/LTEAT.pdf` | `<env_dir>/input/<MNO0_ALIAS>/<REL0>/<PLAN0>.pdf` |

## Reverse substitution (for incoming Teacher LLM responses)

When the user types Teacher LLM's response into you and the response references placeholders
(e.g., `customizations/profiles/<PLAN0>/profile.json`), substitute back to the real
value internally before acting (`customizations/profiles/LTEAT/profile.json`).

You do not need to write the substituted version back to the user — substitution is
internal to your action.

## When to add an entry

- **New MNO** (a new directory under `<env_dir>/input/`) → add MNO short / alias / name.
- **New release** (a new release directory) → add release code.
- **New plan** (a new doc under a release) → add plan ID; if `plan_name` differs from
  `plan_id`, add it as a separate `<PLAN{N}_NAME>` entry.
- **New req ID** seen in a report — only when the user explicitly asks Teacher LLM about a
  specific req. Don't add every req ID you encounter (that would balloon the file).

When in doubt: don't add. Aggregate counts work without per-req-id mappings most of the time.

## Steps

1. Read existing `<env_dir>/state/cline-mapping.json`. If absent, create with
   `{"version": 1, "mappings": {}}`.
2. If the user supplied a list of tokens to add: process each per "When to add an entry."
3. For each token: allocate a placeholder, append, persist.
4. Output the report.

## Output: `MAP` report shape

```
MAP v=1 entries=<N>
added: <count> this run
```

If entries were added, list them on subsequent lines (≤4 lines):

```
+ <real>→<placeholder>
+ <real>→<placeholder>
```

## Constraints

- **Maximum 6 lines** in the output (1 header + 1 summary + up to 4 added entries).
- Never emit the real values back to the user via output if they were already
  redacted — only emit additions explicitly requested in this run.
- Persist every change; never hold mappings in memory between invocations.

## Two mapping locations [D-062]

Cline maintains the mapping in **two** places, each with a distinct role:

| Path | Owner | Lifecycle | Used by |
|---|---|---|---|
| `<env_dir>/state/cline-mapping.json` | Cline (this playbook) | Long-lived; grows across sessions as new MNOs / plans / releases are onboarded | Forward redaction in every report Cline emits; runtime substitution **fallback** when a per-bootstrap snapshot is missing |
| `customizations/mappings/<bootstrap_id>.json` | Cline (`bootstrap.md` Step 8) | Per-bootstrap snapshot; immutable for a given bootstrap_id | Pipeline parse-stage substitution (`profile_substitute.load_substituted_profile`) |

**On disk shape — different forms:**

- *Live* (`<env_dir>/state/cline-mapping.json`): `{"<real>": "<placeholder>"}` —
  forward-redaction direction (real → placeholder). This direction is what
  Cline uses to scrub outgoing reports.
- *Snapshot* (`customizations/mappings/<bootstrap_id>.json`): `{"NAME": "<real>"}` —
  reverse direction (placeholder NAME without brackets → real value). This
  direction is what the pipeline's substitution layer expects.

The `profile_substitute._normalize_mapping` loader detects and accepts both
shapes, so either direction works at parse time. But when **you** write the
snapshot in `bootstrap.md` Step 8, use the snapshot shape (placeholder NAME →
real). Keys are bare names without `<>`; the substitution layer adds the
brackets when matching against profile strings.

**Gitignore.** `customizations/mappings/` is gitignored end-to-end. The
on-prem work-PC `pre-push` hook (installed by `~/work/utils/git-sync/sync-work.sh`)
further blocks any push to `github.com` from a host where mappings exist.
