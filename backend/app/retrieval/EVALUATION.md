# Independence counting: old path vs new path

Recorded **before** stage 6 deleted the old `publisher_family` /
`independent_family_count` counting path. Both counters were still reachable
in commit `27d8139`. This comparison cannot be reproduced once that path is
gone.

## What was compared

- **Old** — `independent_family_count(urls)` in
  `app.scoring.source_independence`. One count per `PUBLISHER_FAMILIES` entry,
  otherwise the registrable domain. It does **not** look at wire credits,
  body similarity, or reprints. This is what Layer 4 used as corroboration
  before the rewrite.
- **New** — `len(resolve_independence(dedupe(hits)))`. Dedupes same-URL
  pages first, then collapses `same_wire`, then `same_owner`, then
  `reprint`. This is `independent_source_count`.

Pages were built as `SearchHit`s with realistic domains and, where relevant,
a shared Reuters/AFP byline plus near-identical body text. The twenty-paper
fixture is the heavily syndicated case.

## Results

| fixture | pages | old `independent_family_count` | new `independent_source_count` | delta (old − new) | new merge reasons |
|---|---:|---:|---:|---:|---|
| twenty_reuters_copies | 20 | 19 | 1 | 18 | same_wire |
| nine_two_mastheads_different_stories | 2 | 1 | 1 | 0 | same_owner |
| three_unrelated_newsrooms | 3 | 3 | 3 | 0 | none |
| unmapped_plus_bbc | 3 | 3 | 3 | 0 | none |
| five_reuters_plus_bbc_original | 6 | 5 | 2 | 3 | none, same_wire |
| reuters_and_afp_same_text | 2 | 2 | 2 | 0 | none |
| bbc_com_and_bbc_co_uk | 2 | 1 | 1 | 0 | same_owner |
| same_url_twice_two_adapters | 2 | 1 | 1 | 0 | none |
| empty | 0 | 0 | 0 | 0 | n/a |

## How to read this

The headline result is **twenty_reuters_copies**. Twenty papers carry one
Reuters story. The old counter reports **19 independent sources** (SMH and
The Age share the `nine_au` family, so it already collapsed those two
mastheads — and nothing else). The new counter reports **1**, with
`merge_reason=same_wire`. That is an 18-source overcount on the old path:
the journalist would have been told that nineteen newsrooms corroborated a
story that one agency wrote.

**five_reuters_plus_bbc_original** is the mixed case: five syndicated copies
plus one BBC piece with different text. Old: 5. New: 2 (the wire group, and
the BBC original). The BBC report is kept as a second source, which is the
correct reading — it is independent of the wire.

**reuters_and_afp_same_text** (SMH crediting Reuters, Irish Times crediting
AFP, same body) stays 2 = 2. Two agencies covering one event is real
corroboration; sharing text is not enough to merge them, because the wire
credits differ and reprint collapsing does not fire when a wire credit is
present.

**nine_two_mastheads_different_stories** and **bbc_com_and_bbc_co_uk** agree
old and new, both collapsing by ownership. The rewrite does not invent that
grouping; it adds wire and reprint collapsing on top of it, and records
*why*.

**unmapped_plus_bbc** agrees 3 = 3. An absent domain stays independent on
both paths. The new map's incompleteness therefore overstates corroboration
in the same direction the old map did; it does not silently erase outlets.

**three_unrelated_newsrooms** agrees 3 = 3. When there is no wire, no shared
owner, and no reprint, the new path does not reduce the count.

## What this is not

This is not a claim that the new count is the number of true reports, or
that a story with `independent_source_count == 1` is false. It is only the
demonstration that counting pages (or counting mastheads without looking at
the wire credit) treats syndication as corroboration, and that the new
path stops doing that.
