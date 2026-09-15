"""Generate a high-level Excalidraw diagram for Layer 3."""

from pathlib import Path

from _lib import BLUE, GREEN, ORANGE, PALE_BLUE, RED, VIOLET, YELLOW, Diagram

OUT = Path(__file__).with_name("03-verification-layer.excalidraw")


def build() -> Diagram:
    d = Diagram()
    d.header(
        "Layer 3 — Retrieval and Independence",
        "NewsAuth · Thesis B · COMP4092     Find who else published on this, and how many of them are genuinely separate newsrooms. Volume is not corroboration. A failed, skipped, or empty search is a coverage gap, never a signal of falsity.",
    )
    d.pipeline_chips(60, 132, active=3)

    d.box(
        "from-l2",
        420,
        200,
        1100,
        88,
        "From Layer 2 — claims, headline, entities, date window",
        "This layer does not re-read the article to judge it. It turns that structure into searches, then counts newsrooms rather than pages.",
        fill=PALE_BLUE,
        title_size=18,
        body_size=15,
    )

    d.box(
        "select",
        60,
        316,
        900,
        108,
        "Select searchable claims",
        "Top-k by how searchable a claim is, not how true it is. Unselected claims are unsearched — a budget decision, not a finding.",
        fill=BLUE,
        title_size=18,
        body_size=15,
    )
    d.box(
        "freeze",
        996,
        316,
        944,
        108,
        "Build queries, then freeze them",
        "planned_queries is written onto the envelope BEFORE any HTTP call. Re-run replays that plan verbatim so a later answer is comparable.",
        fill=YELLOW,
        title_size=18,
        body_size=15,
    )

    d.box(
        "gate",
        60,
        456,
        1880,
        96,
        "Capability gate — once, in the adapter base class",
        "Article older than the source’s archive, missing API key, or a known unsupported language → skipped_out_of_range / skipped_no_key. Unknown date or language never skips. These paths never return not_found: that would say “nobody else has this story” when the truth is “we never looked”.",
        fill=ORANGE,
        title_size=18,
        body_size=15,
    )

    d.box(
        "ladder",
        60,
        584,
        450,
        220,
        "Existence ladder",
        "Quoted headline, then loose, then keywords. Stop at the first rung that hits. Empty ladder (no headline) is not_planned, distinct from exhausted (looked, found nothing).",
        fill=BLUE,
        title_size=17,
        body_size=14,
    )
    d.box(
        "claims",
        530,
        584,
        450,
        220,
        "Claim and event searches",
        "NewsAPI, Guardian, GNews, Newsdata, GDELT — all in flight at once via asyncio.gather. A failing adapter reports error and does not abort the others.",
        fill=BLUE,
        title_size=17,
        body_size=14,
    )
    d.box(
        "factcheck",
        1000,
        584,
        450,
        220,
        "Prior ClaimReview",
        "Google Fact Check Tools. The reviewer’s rating is kept verbatim and attributed to them. It is not mapped onto NewsAuth’s output.",
        fill=VIOLET,
        title_size=17,
        body_size=14,
    )
    d.box(
        "wiki",
        1470,
        584,
        470,
        220,
        "Entity grounding",
        "Wikipedia / Wikidata, one lookup per person, organisation, or place. A miss is obscurity or a spelling variant — never evidence the name was invented.",
        fill=VIOLET,
        title_size=17,
        body_size=14,
    )

    d.box(
        "dedupe",
        60,
        836,
        600,
        168,
        "Dedupe → documents",
        "Same canonical URL, then near-identical text from the SAME publisher. Twenty papers running one wire story stay twenty documents. Deduping pages is not counting sources.",
        fill=GREEN,
        title_size=17,
        body_size=14,
    )
    d.box(
        "indep",
        680,
        836,
        620,
        168,
        "Independence → sources",
        "Collapse non-independent pages: same_wire, then same_owner, then reprint. Each group carries merge_evidence naming the outlets and the reason, so a journalist can disagree with the merge.",
        fill=GREEN,
        title_size=17,
        body_size=14,
    )
    d.box(
        "rank",
        1320,
        836,
        620,
        168,
        "Rank by textual similarity",
        "Cosine of claim vs title+snippet. ranking_method records embedding or char-ngram, because those scores are not comparable. Ordering is not agreement, and not a verdict.",
        fill=GREEN,
        title_size=17,
        body_size=14,
    )

    d.box(
        "coverage",
        60,
        1036,
        1880,
        140,
        "Coverage report — three ways a run can be narrower than it looks",
        "1. Capability-gate notes: which checks never ran, and why (unknown date, unknown language).\n"
        "2. Ladder outcome: not_planned (never looked) versus exhausted (looked, found nothing).\n"
        "3. Keyword rung skipped: headline was all stopwords, so the broadest query was never built.\n"
        "Read this before reading any count. A low count from a narrow search is not a finding about the article.",
        fill=YELLOW,
        title_size=18,
        body_size=14,
    )

    d.box(
        "payload",
        60,
        1208,
        1240,
        140,
        "RetrievalPayload",
        "document_count = pages. independent_source_count = newsrooms. existence_class keeps out_of_range distinct from not_found. Counts are derived from their lists, so they cannot drift.",
        fill=PALE_BLUE,
        title_size=18,
        body_size=15,
    )
    d.box(
        "shim",
        1320,
        1208,
        620,
        140,
        "Compat shim — transitional",
        "Also fills the old queries / evidence_items / wiki_hits / tool_results / corroboration.existence fields so Layers 4–7 keep running. out_of_range is mapped to not_found here only. Stage 6 deletes the shim.",
        fill=ORANGE,
        title_size=17,
        body_size=14,
        dashed=True,
    )

    d.box(
        "review",
        60,
        1380,
        900,
        120,
        "Journalist reviews this layer, then chooses",
        "Proceed → Layer 4 compares each claim against these documents, counted as newsrooms.\n"
        "Re-run replays the frozen queries. Ask can only use this layer’s output.",
        fill=ORANGE,
        title_size=17,
        body_size=15,
    )
    d.box(
        "next",
        996,
        1380,
        360,
        120,
        "Next: Layer 4",
        "Evidence analysis\n(DeBERTa NLI + Gemini)",
        fill=BLUE,
        title_size=17,
        body_size=15,
    )
    d.box(
        "not",
        1388,
        1380,
        492,
        120,
        "This layer does not",
        "Score true/false, run NLI, or decide authenticity. Empty or skipped sources are uncertainty, never a mark against the story.",
        fill=RED,
        title_size=17,
        body_size=15,
    )

    d.text(
        "footer",
        60,
        1532,
        "Source of truth: backend/app/retrieval/run.py, planner.py, ladder.py, independence.py, ranking.py, adapters/,\n"
        "backend/app/schemas/retrieval.py, backend/app/pipeline/orchestrator.py (LAYER_TITLES display only; trace id stays “verification”), "
        "src/components/layerOutputs.tsx. Tests: backend/tests/test_retrieval_integration.py, test_independence.py, test_retrieval_adapters.py.",
        size=12,
        color="#868e96",
        width=1880,
    )

    d.arrow("a-in-select", "from-l2", "select")
    d.arrow("a-select-freeze", "select", "freeze", src_side="right", dst_side="left")
    d.arrow("a-freeze-cap", "freeze", "gate")
    d.arrow("a-cap-ladder", "gate", "ladder", drop="dst")
    d.arrow("a-cap-claims", "gate", "claims", drop="dst")
    d.arrow("a-cap-fc", "gate", "factcheck", drop="dst")
    d.arrow("a-cap-wiki", "gate", "wiki", drop="dst")
    d.arrow("a-ladder-dedupe", "ladder", "dedupe", drop="src")
    d.arrow("a-claims-dedupe", "claims", "dedupe", drop="src")
    d.arrow("a-dedupe-indep", "dedupe", "indep", src_side="right", dst_side="left")
    d.arrow("a-indep-rank", "indep", "rank", src_side="right", dst_side="left")
    d.arrow("a-rank-cov", "rank", "coverage")
    d.arrow("a-cov-pay", "coverage", "payload")
    d.arrow("a-pay-shim", "payload", "shim", src_side="right", dst_side="left")
    d.arrow("a-pay-review", "payload", "review")
    d.arrow("a-review-next", "review", "next", src_side="right", dst_side="left")

    return d


def main() -> None:
    build().write(OUT)


if __name__ == "__main__":
    main()
