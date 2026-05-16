# references-handling

**Status:** in-flight
**Opened:** 2026-05-15
**Landed:**
**Assignees:** kurnoolion
**Target modules:** parser, resolver, profiler
**Active phase:**

## Summary

Build reference-list parsing (D-059 follow-through). Wire `RequirementTree.reference_list_map` ingestion in the parser so a bibliography / references section's entries land as `{entry_number: {spec, section, release, ...}}`, then teach the resolver to consume that map when it encounters `reference_spec` citations with `style=indirect` (e.g. `[5]`). STATUS line 200 flags this as deferred until the first corpus with a bibliography section + annotated indirect spec citations arrives — work begins when that corpus lands.

## Notes
