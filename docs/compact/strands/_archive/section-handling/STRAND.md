# section-handling

**Status:** landed
**Opened:** 2026-05-16
**Landed:** 2026-05-16
**Assignees:** kurnoolion
**Target modules:** web, parser
**Active phase:**

## Summary

Some sections that the parser correctly classifies (non-empty `section_number`, `title`, `req_id` in `<env_dir>/out/parse/<doc>_tree.json`) don't show as `SECTION_HEADING` annotations on the Review tab. Root cause is in `core/src/web/routes/parse_review.py`'s text-keyed reverse-mapping: `text_to_idx` is keyed by full IR block text (e.g. `"1.2.3.4 <TITLE> <MNO0>_REQ_..."`) while the lookup uses just `req.title` (e.g. `"<TITLE>"`). Two fix shapes available: (1) web-only — normalize the keys to match title form; (2) parser-side — carry the originating `block_idx` on `Requirement` so web does a direct idx lookup.

## Notes

Landed on 2026-05-16 with 0 promoted decisions. Shipping commit: `5cf299f`. No DECISIONS entry — treated as a basic implementation fix per user verdict (option 1 at land time).
