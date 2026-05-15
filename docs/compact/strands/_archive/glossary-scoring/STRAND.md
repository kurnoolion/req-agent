# glossary-scoring

**Status:** landed
**Opened:** 2026-05-16
**Landed:** 2026-05-15
**Assignees:** kurnoolion
**Target modules:** profiler, parser, web, profile_miner
**Active phase:**

## Summary

Build a parallel `GlossaryDetection` profile field that mirrors `RevhistDetection` — same three-signal scoring shape (heading-text match + vocabulary tokens + cell-content fingerprint) but tuned for glossary tables (col-0 short-uppercase acronym tokens, col-1 prose definitions; vocab tokens like acronym/abbrev/definition/term/expansion/meaning). When enabled, runs as a third detection path after `definitions_section_pattern` (label match on section title) and `heading_detection.definitions_table_header_pattern` (joined-header regex match) — both shipped 2026-05-13/14. Current corpus shows 135/135 docs missing glossary because section titles don't match the default `(?i)acronym|definition|glossary` regex; signal-based detection should close most of that gap.

## Notes

Landed on 2026-05-15 with 3 promoted decisions: D-079, D-080, D-081. Scope pivoted from "build full `GlossaryDetection` three-signal scorer" to "density-gate the existing regex (vocab signal in isolation) + fix extractor bugs that hid glossary tables (1×1 wrapper preservation, nested-table walk)." The full `GlossaryDetection` profile field remains deferred — open a follow-up strand if the corpus shows missed glossaries from the regex alone (D-079 only suppresses false positives; it doesn't help when the regex misses entirely).
