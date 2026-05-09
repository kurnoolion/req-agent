# Annotation schema

**Purpose**: define the JSON shape humans use to mark structural elements in corpus
documents so Cline can derive initial detection rules. This is a **reference** — read by
humans (to know what to write) and by Cline (to know how to ingest). Not invoked as a
playbook.

**Bootstrap-only feature**: bootstrap annotations capture POSITIVE examples only. False
positives are discovered after the parser runs, via the Parse Review feedback loop
(`feedback-loop.md`). This is intentional — negative annotations are tedious and humans
catch them better at parse-output review time.

## File location

One annotation file per source document:

```
<env_dir>/annotations/<plan>_annotations.json
```

Lives on-prem only, never in git.

## Schema

```json
{
  "version": 1,
  "doc_path": "<env_dir>/input/<MNO>/<RELEASE>/<plan>.{pdf,docx,xlsx}",
  "annotations": [
    { ... per-annotation entries below ... }
  ]
}
```

## Per-annotation entry

Common fields:

| Field | Required | Notes |
|---|---|---|
| `id` | yes | unique within the file (e.g., `ann_001`) |
| `kind` | yes | one of the kinds below |
| `region` | yes | location, format depends on doc type (see "Region format") |
| `notes` | no | ≤30 char structural note; never verbatim corpus content |

Optional kind-specific fields are listed under each kind's section.

## Supported kinds

### `section_heading`

A heading that introduces a section. Critical for parser tree structure.

Optional fields:
- `depth`: integer (1 = chapter, 2 = section, 3+ = subsection)
- `section_number`: the actual numeric label (`"1.2.3"`) — this is structural, not content
- `is_numbered`: bool
- `title_char_count`: integer (length-only signal, no content)

### `req_id`

A requirement-identifier token. Drives requirement extraction.

Optional fields:
- `placement`: `"leading"` (req_id at start of req) or `"trailing"` (req_id at end)
- `format_hint`: structural shape, e.g., `"<MNO>_REQ_<PLAN>_<DIGITS>"` — use placeholders
  per `02-content-safety.md`

### `toc`

A table-of-contents region. Pages or page ranges that are TOC, not body.

Optional fields:
- `pattern_hint`: e.g., `"leader-dot-page"`, `"indented-leveled"`, `"plain-list"`

### `strikethrough`

A struck region (deleted-but-visible). Triggers strike-handling in the parser.

Optional fields:
- `subkind`: `"full_paragraph"` | `"table_row"` | `"partial_cell"` | `"section_heading"`
- `visual`: `"line"` (line-strike) | `"font_flag"` (font's strike attribute) | `"both"`

### `version_history` / `revision_history`

A revision-history heading + the rows that follow.

Optional fields:
- `kind_subtype`: `"heading_only"` (mark the heading) or `"full_block"` (mark the heading
  + the version table)

### `definitions`

A definitions / acronyms section.

Optional fields:
- `layout`: `"paragraph_list"` | `"two_col_table"` | `"three_col_table"` | `"inline_glossary"`

### `applicability`

An applicability marker (LTE / 5G / form-factor / device-class tag).

Optional fields:
- `position`: `"after_heading"` | `"inline_in_para"` | `"separate_block"`

### `priority`

A priority marker (mandatory / optional / conditional / etc).

Optional fields:
- `position`: same as applicability

### `references`

A reference to another section, plan, or public spec.

Required additional field:
- `subkind`: `"intra_doc"` | `"cross_doc"` | `"spec"`

Optional fields:
- `target_kind`: `"section_number"` | `"req_id"` | `"spec_ts_section"`
- `inline`: bool (true if the reference is inline within a paragraph)

## Region format (per doc type)

The `region` field shape depends on the source document type. Cline detects from
`doc_path` extension.

### PDF / DOCX (flat IR — single sequential index across paragraphs / headings / tables / images)

The PDF and DOCX extractors both produce the same `DocumentIR` with a single
`block.position.index` numbered 0..N across the whole document. Annotation
regions index that flat list directly.

Single block:
```json
"region": { "block_indices": [142] }
```

Range of blocks (for TOC regions, definitions sections, version-history blocks):
```json
"region": { "block_indices": [12, 13, 14, 15, 16] }
```

Row-precise within a single table block:
```json
"region": {
  "block_index": 142,
  "row_range": [3, 5]             // rows within block.rows (header excluded; 0-based)
}
```

### XLSX

```json
"region": {
  "sheet": "Requirements",
  "row_range": [42, 42]
}
```
or
```json
"region": {
  "sheet": "Requirements",
  "cells": ["B42", "C42"]
}
```

## Annotation guidance

- **Aim for 3–5 documents** per stage's first bootstrap. Cline derives rules per kind from
  the union of annotations across docs.
- **Aim for 5–10 examples per kind** per document — enough variety for Cline to extract a
  general rule, not so many it becomes tedious.
- **Don't include verbatim content in `notes`** — describe structure, not text.
  Good: `"deep nesting"`, `"struck row in table"`. Bad: any quoted heading or phrase.
- **Pre-existing files**: if a `<plan>_annotations.json` already exists, Cline appends new
  entries with new IDs. Don't overwrite.

## Validation

When Cline reads an annotation file, it validates:

1. Schema version (currently `1`)
2. `doc_path` exists and is under `<env_dir>/input/`
3. Each annotation has `id`, `kind`, `region` and the kind is in the supported list
4. Region format matches the doc type's extension
5. No `notes` longer than 30 chars or containing what looks like quoted prose

Validation failures are reported in the BOOTSTRAP report (one line per failure, ≤5 lines
total — if more, the report says "skipping further validation errors" and the user fixes).

## Web UI

The annotation file is now populated via the **Bootstrap** tab on the **Parse** page in
NORA's web UI (`/parse-review`). Selecting a DOCX from the dropdown opens a 3-pane editor:

- **IR blocks** (left) — sequential `block.position.index` list; click `+` on a block to
  annotate. Shift-click a second block extends a multi-block range.
- **DOCX preview** (middle) — formatted-as-HTML preview with `data-block-idx` attributes
  aligned to the IR pane. Reference only — clicks happen on the IR side.
- **Annotations** (right) — list grouped by kind; click an entry to scroll to the region
  or edit; ✗ deletes.

Tables in the IR pane have row-pickers — click a row inside a table to start a row-range
selection; shift-click another row to extend it; the resulting annotation gets
`{ block_index, row_range }`.

Save writes `<env_dir>/annotations/<plan>_annotations.json` atomically; server-side
schema validation rejects malformed payloads with a 400 + per-field error list.

PDF and XLSX support are not yet wired into the UI; hand-write the JSON for those
formats until they land.
