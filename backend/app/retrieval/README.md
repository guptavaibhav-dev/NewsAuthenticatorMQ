# Layer 3 — Retrieval and Independence

Layer 3 finds out what else has been published about a submitted article, and
how many genuinely separate newsrooms are behind those pages. It does not
decide whether the article is true.

It plans searches from Layer 2's claims, headline, and entities; freezes that
plan on the envelope **before** any HTTP call; asks each adapter through a
shared capability gate; then dedupes pages, collapses syndication and shared
ownership, ranks what remains, and records coverage. Empty, skipped, or failed
searches are coverage gaps, never a signal of falsity.

The trace id is still `"verification"` so the frontend filter keeps working.
The display title is "Retrieval and Independence".

## `document_count` vs `independent_source_count`

Syndication means one wire report can appear as fifty pages under fifty
mastheads. Counting pages would present that as fifty confirmations.

| Field | What it counts | What it is not |
|---|---|---|
| `document_count` | Distinct retrieved pages (after URL dedupe) | Corroboration |
| `independent_source_count` | Newsrooms remaining after wire, owner, and reprint collapse | A quality rating |

Only `independent_source_count` bears on corroboration. The two numbers are
derived from list lengths so they cannot drift. A measured before/after on
fixtures, including a twenty-paper Reuters syndication, is in
[`EVALUATION.md`](EVALUATION.md).

## How to add an adapter

1. Subclass `SourceAdapter` in `backend/app/retrieval/adapters/`.
2. Declare a `Capability`: `max_age_days` (or `None` if ungated), `languages`,
   `regions`, `searches_full_text`, `requires_key`. Every reach limit must be
   stated; omitting one is a validation error.
3. Implement `search()`. Return hits plus an `AdapterReport`. Capability
   skips (`skipped_out_of_range`, `skipped_no_key`) are produced by the base
   class gate — do not map them to `empty` or invent an existence class.
   Adapters never return `not_found`; that is an existence-class outcome of
   the ladder, not an HTTP status.
4. Build hits with `build_hit()`, which imports Layer 1's `canonical_url` and
   `publisher_identity`. Do not reimplement canonicalisation.
5. Register article-search adapters in `news_adapters()` in
   `adapters/__init__.py` so an unconfigured source still appears as
   `skipped_no_key`. Fact-check and Wikipedia are wired separately in
   `run.py` because they are not article search.

Tests use `httpx.MockTransport` and `asyncio.run`. Do not add pytest-asyncio
or respx.

## How to extend the ownership map

Edit `backend/app/data/publisher_ownership.json`. Add

```json
"example.com": "example_group"
```

under `"ownership"`. The key is the registrable domain; the value is a coarse
group id used only for collapsing, never as a quality mark.

The file is loaded at runtime. A missing domain is counted as independent —
that overstates corroboration on purpose, because the opposite guess would
silently erase real independent reporting. Do not infer a parent from a name
or a substring. There is no code path that writes this file.

## Limitations

- **The ownership map is incomplete** (154 domains, 68 groups). An absent
  domain is counted as independent, so `independent_source_count` can be too
  high.
- **Wire detection depends on bylines** that are often absent. A syndicated
  copy with no credit and rewritten lead will not collapse as `same_wire`.
- **Language coverage is uneven.** Adapters declare the languages they
  search; several are English-only or unlisted.
- **Article language is not detected at all.** `article_context` always
  passes `article_language=None`, so language capability checks never fire
  (unknown is not treated as unsupported). Age checks also never fire today:
  `published_at` is always `None` on the context.
- **GNews and Newsdata are ungated** (`gnews_max_age_days` and
  `newsdata_max_age_days` default to `None`) because no current archive limit
  could be verified. Operators who know their plan should set them.
- **The 0.22 relevance floor and 0.88 near-duplicate threshold** were tuned
  on character-trigram cosine and do not transfer to semantic embeddings.
  `ranking_method` is recorded beside every score for that reason.

## Config

Values this layer introduced, with defaults.

| Setting | Default | Justification |
|---|---|---|
| `retrieval_top_k_claims` | `5` | **Arbitrary.** How many Layer 2 claims get retrieval queries. Intended for experimental determination; not derived from a measured budget. |
| `planner_use_llm` | `False` | Justified. The deterministic planner is reproducible; a rewrite is only accepted whole, and is off unless an operator opts in. |
| `newsapi_max_age_days` | `30` | From [NewsAPI pricing](https://newsapi.org/pricing), checked **2026-09-15**: free Developer plan “Search articles up to a month old”. 30 rather than 29 so an over-tight bound does not invent `out_of_range` for articles the source can still reach. |
| `gnews_max_age_days` | `None` | Deliberately ungated — archive limit not verified. |
| `newsdata_max_age_days` | `None` | Deliberately ungated — archive limit not verified. |
| `gdelt_max_records` | `25` | Arbitrary request size for GDELT DOC 2.0. GDELT's index starts in 2017, so no age gate is applied. |

Module constants (not Settings fields): `WIRE_SERVICES` in `config.py`;
`RELEVANCE_FLOOR = 0.22` and `NEAR_DUPLICATE_THRESHOLD = 0.88` in
`ranking.py` (char-trigram-tuned, see Limitations); Jaccard
`DUPLICATE_JACCARD = 0.9`, `WIRE_JACCARD = 0.8`, `REPRINT_JACCARD = 0.9` in
`independence.py`.

Leftovers from the deleted sequential Layer 3, unused by this path:
`max_evidence_items = 12`, `near_duplicate_threshold = 0.88` on `Settings`.
