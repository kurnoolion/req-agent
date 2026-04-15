# Contributing Guide

This guide is for team members working on verifying and improving the telecom requirements AI pipeline.

## Workflow Overview

```
Admin creates environment → Member runs pipeline → Reviews artifacts
→ Makes corrections → Re-runs → Reports results (compact format)
```

## Getting Started

1. Clone the repo and run setup:
   ```bash
   git clone <repo-url>
   cd req-agent
   ./setup_env.sh
   ```

2. Ask the admin for your environment name, then check it:
   ```bash
   python -m src.env.env_cli show <your-env-name>
   ```

3. Initialize your workspace:
   ```bash
   python -m src.env.env_cli init <your-env-name>
   ```

4. Place your documents in `<document_root>/documents/`

5. Run the pipeline:
   ```bash
   python -m src.pipeline.run_cli --env <your-env-name>
   ```

## File Ownership

### Auto-generated (DO NOT edit directly)
These files are produced by the pipeline. Edits will be overwritten on the next run.

| Directory | Contents |
|---|---|
| `output/extracted/` | Document IR JSON files |
| `output/parsed/` | Requirement tree JSON files |
| `output/resolved/` | Cross-reference manifests |
| `output/taxonomy/` | Feature extraction (per-doc + unified) |
| `output/standards/` | Downloaded 3GPP specs + parsed sections |
| `output/graph/` | Knowledge graph JSON |
| `output/vectorstore/` | ChromaDB + embeddings |
| `output/eval/` | Evaluation reports |
| `reports/` | Pipeline run reports |

### Human-editable (your contribution goes here)

| File/Directory | What to put here |
|---|---|
| `documents/` | Source documents (PDF, DOCX, XLS, XLSX) |
| `corrections/profile.json` | Corrected document profile (copy from `output/profile/`, fix, place here) |
| `corrections/taxonomy.json` | Corrected taxonomy (copy from `output/taxonomy/taxonomy.json`, fix, place here) |
| `eval/*.xlsx` | Your Q&A evaluation pairs (see format below) |

## Correction Workflow

### Correcting a Document Profile

1. Run the pipeline through the `profile` stage
2. Review `output/profile/profile.json`
3. Copy it to `corrections/profile.json`
4. Edit the copy — fix heading levels, req ID patterns, zones, etc.
5. Re-run the pipeline — it will use your corrected profile automatically
6. Report what you changed (see Reporting Format below)

### Correcting the Taxonomy

1. Run the pipeline through the `taxonomy` stage
2. Review `output/taxonomy/taxonomy.json`
3. Copy it to `corrections/taxonomy.json`
4. Edit — rename features, remove incorrect ones, add missing ones
5. Re-run the pipeline from `graph` stage onward
6. Report what you changed

## Evaluation Q&A Format (Excel)

Create an `.xlsx` file in `eval/` with these columns:

| Column | Required | Description | Example |
|---|---|---|---|
| `question_id` | Yes | Unique ID | `Q_CUSTOM_01` |
| `category` | Yes | One of: `single_doc`, `cross_doc`, `feature_level`, `standards_comparison`, `traceability` | `cross_doc` |
| `question` | Yes | The question text | `What are the T3402 timer requirements?` |
| `expected_plans` | Yes | Comma-separated plan IDs | `LTEDATARETRY,LTEB13NAC` |
| `expected_req_ids` | No | Comma-separated req IDs | `VZ_REQ_LTEDATARETRY_7748` |
| `expected_features` | No | Comma-separated features | `DATA_RETRY,LTE_ATTACH` |
| `expected_standards` | No | Comma-separated specs | `3GPP TS 24.301` |
| `expected_concepts` | No | Comma-separated concepts | `T3402,timer,retry` |
| `min_plans` | No | Min plans expected (default: 1) | `2` |
| `min_chunks` | No | Min chunks expected (default: 1) | `3` |

## Reporting Results

After running the pipeline, report results using these compact formats.

### Pipeline Report
The pipeline outputs a compact report at the end of each run. Copy the block between the `───` lines and paste it.

Example:
```
RPT profiler-review 2026-04-15T14:30
HW CPU=Intel Ultra 9(22c) RAM=32G GPU=RTX4060(16G)
MDL gemma4:e4b
EXT OK 12s docs=8 blk=4521 tbl=234
PRF OK 3s lvl=4 rpat=2 zone=3
PRS OK 9s req=890 dep=7 docs=8
ERR none
```

### Quality Check (type this after reviewing artifacts)

**Profile QC:**
```
QC my-env profile
lvl=Y rpat=Y zone=Y body=Y hf=Y
miss: none
notes: heading level 3 threshold too high
```

**Taxonomy QC:**
```
QC my-env taxonomy
feat=16 correct=14 wrong=1 miss=3
wrong: IMS_REGISTRATION(appears in all docs, mock artifact)
miss: VOLTE_HANDOVER, SMS_RETRY, ATTACH_GUARD
notes: overall good except mock artifacts
```

**Eval QC:**
```
QC my-env eval
q=18 pass=14 fail=4
fail: Q_CD_01(missing LTEB13NAC), Q_STD_02(wrong spec version)
notes: cross-doc questions weakest
```

### Correction Feedback (type this after making corrections)

**Profile fix:**
```
FIX my-env profile
heading_threshold: 14.0 -> 13.0
req_pattern: added "ATT_REQ_\w+"
notes: B13 doc has different heading sizes
```

**Taxonomy fix:**
```
FIX my-env taxonomy
added=3 removed=1 renamed=2
add: VOLTE_HANDOVER(keywords: handover,ho,mobility)
remove: GENERIC_ATTACH
rename: DATA_RETRY->LTE_DATA_RETRY, SMS->LTE_SMS
notes: removed mock artifacts, added real features
```

## Show Templates

To see the QC or correction template for any stage:
```bash
python -m src.pipeline.run_cli --qc-template profile
python -m src.pipeline.run_cli --qc-template taxonomy
python -m src.pipeline.run_cli --fix-template taxonomy
```

## Environment Directory Structure

```
<document_root>/
├── documents/        # YOUR source documents go here
├── corrections/      # YOUR corrected artifacts go here
│   ├── profile.json  # Corrected document profile (optional)
│   └── taxonomy.json # Corrected taxonomy (optional)
├── eval/             # YOUR Q&A eval pairs go here
│   └── questions.xlsx
├── output/           # Auto-generated pipeline outputs
│   ├── extract/
│   ├── profile/
│   ├── parse/
│   ├── resolve/
│   ├── taxonomy/
│   ├── standards/
│   ├── graph/
│   ├── vectorstore/
│   └── eval/
└── reports/          # Auto-generated pipeline reports
```

## Common Commands

```bash
# List available stages
python -m src.pipeline.run_cli --list-stages

# Run specific stages
python -m src.pipeline.run_cli --env my-env --start extract --end parse

# Re-run from taxonomy with corrections
python -m src.pipeline.run_cli --env my-env --start graph --end eval

# Check hardware and model recommendation
python -m src.pipeline.run_cli --detect-hw

# Show environment details
python -m src.env.env_cli show my-env

# List all environments
python -m src.env.env_cli list
```
