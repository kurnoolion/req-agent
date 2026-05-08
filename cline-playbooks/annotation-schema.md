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

### PDF

```json
"region": {
  "pages": [12]                   // single-page region
}
```
or
```json
"region": {
  "pages": [5, 6, 7]              // multi-page region
}
```
or
```json
"region": {
  "page": 12,
  "bbox": [72, 320, 540, 340]     // x1, y1, x2, y2 in PDF points
}
```
or
```json
"region": {
  "page": 12,
  "line_range": [42, 42]          // line-numbered within the page (extractor's IR)
}
```

### DOCX

```json
"region": {
  "paragraph_indices": [142]      // single paragraph (zero-based)
}
```
or
```json
"region": {
  "paragraph_indices": [142, 143, 144]
}
```
or
```json
"region": {
  "table_index": 7,
  "row_range": [3, 5]             // rows within table 7
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

## Web UI (planned, not built yet)

The annotation files will eventually be populated by a NORA web UI page that renders the
extracted IR (PDF / DOCX / XLSX → unified IR view) and lets the user click-to-mark regions.
Until that's built, hand-write the JSON or use a simple ad-hoc CLI.

When the web UI lands, the schema doesn't change — only the input ergonomics.
