# glossary-scoring

**Status:** in-flight
**Opened:** 2026-05-16
**Landed:**
**Assignees:** kurnoolion
**Target modules:** profiler, parser, web, profile_miner
**Active phase:**

## Summary

Build a parallel `GlossaryDetection` profile field that mirrors `RevhistDetection` — same three-signal scoring shape (heading-text match + vocabulary tokens + cell-content fingerprint) but tuned for glossary tables (col-0 short-uppercase acronym tokens, col-1 prose definitions; vocab tokens like acronym/abbrev/definition/term/expansion/meaning). When enabled, runs as a third detection path after `definitions_section_pattern` (label match on section title) and `heading_detection.definitions_table_header_pattern` (joined-header regex match) — both shipped 2026-05-13/14. Current corpus shows 135/135 docs missing glossary because section titles don't match the default `(?i)acronym|definition|glossary` regex; signal-based detection should close most of that gap.

## Notes
