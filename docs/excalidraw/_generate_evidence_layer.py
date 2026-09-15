"""Generate a high-level Excalidraw diagram for Layer 4."""

from pathlib import Path

from _lib import BLUE, GREEN, ORANGE, PALE_BLUE, RED, VIOLET, YELLOW, Diagram

OUT = Path(__file__).with_name("04-evidence-layer.excalidraw")


def build() -> Diagram:
    d = Diagram()
    d.header(
        "Layer 4 — Evidence Analysis",
        "NewsAuth · Thesis B · COMP4093     Compare each claim against retrieved snippets. Two engines, then a deterministic fuse. No authenticity score.",
    )
    d.pipeline_chips(60, 132, active=4)

    d.box(
        "from-l3",
        60,
        200,
        1880,
        88,
        "From Layer 3 — claims × retrieved snippets",
        "Atomic claims from Layer 2, plus ranked snippets, existence class, and independent sources from Layer 3. The premise Engine A will see is a snippet, not the article.",
        fill=PALE_BLUE,
        title_size=18,
        body_size=15,
    )

    d.box(
        "nli-sel",
        60,
        316,
        900,
        88,
        "Engine A — per pair",
        "Each checkworthy claim × the top ranked snippets (max_evidence_items, default 12), not every retrieved page. One NLI call per pair, run concurrently with Engine B.",
        fill=YELLOW,
        title_size=16,
        body_size=15,
    )
    d.box(
        "llm-sel",
        1020,
        316,
        860,
        88,
        "Engine B — one batched call",
        "Same snippet window as Engine A, every claim (checkworthy or not), one request. Runs at the same time as Engine A. Not per pair.",
        fill=YELLOW,
        title_size=16,
        body_size=15,
    )

    d.box(
        "nli",
        60,
        432,
        900,
        400,
        "Engine A — DeBERTa MNLI (non-generative)",
        "Preferred: DeBERTa. If that is down: BART MNLI, then lexical overlap.\n"
        "\n"
        "The premise is a search snippet (usually 500–800 characters). For GDELT it is often the title alone. Not the article — that is why false-neutrals happen.\n"
        "\n"
        "Each pair returns entailment · contradiction · neutral, with a confidence.\n"
        "\n"
        "The lexical fallback cannot detect contradiction in general. When it runs, the payload records that so a zero is not read as none found.\n"
        "If there are no pairs, that is recorded as empty — not as false.",
        fill=BLUE,
        title_size=18,
        body_size=15,
    )

    d.box(
        "llm",
        1020,
        432,
        860,
        400,
        "Engine B — blinded Gemini (then Claude)",
        "Blinded from NLI labels, existence class, title-match strength, relevance, merge reason, and wire credit. Sees outlet, date, URL, title, snippet.\n"
        "\n"
        "For each claim it lists which source_ids support, refute, or are unrelated, plus slot clashes (date, place, number, actor).\n"
        "\n"
        "Invented source IDs are dropped. A response that cited only invented IDs is a non-response, not “no stance”. Temperature is 0.0; gemini-3* cannot pin sampling, and that is recorded.",
        fill=VIOLET,
        title_size=18,
        body_size=15,
    )

    d.box(
        "fuse",
        60,
        860,
        1880,
        248,
        "Deterministic fusion — a rule, not a third model",
        "Count support and contradiction by independent source, not by URL or masthead (twenty syndicated copies are one newsroom).\n"
        "Join misses against Layer 3 groups are counted: a miss inflates the independent-source count, which is then an upper bound.\n"
        "Agreement: convergent · contested · NLI-only · LLM-only · none. Contradiction counts are withheld when Engine A could not detect polarity.\n"
        "Empty paths are not_assessed, never no_corroboration_found. not_found (looked, nothing) and out_of_range (never looked) stay distinct.\n"
        "Fusion is a pure function of its input. Engine B sampling may be unpinned, so the layer is not reproducible even though fusion is.",
        fill=GREEN,
        title_size=18,
        body_size=15,
    )

    d.text("out-label", 60, 1140, "What this layer produces", size=16, color="#495057")
    cards = [
        ("out-matrix", "Claim–evidence matrix", "Each cell: NLI label\nplus LLM stance"),
        ("out-agree", "Engine agreement", "convergent, contested,\nor one engine only"),
        ("out-fam", "Independent sources", "Newsroom counts; upper\nbound if join misses"),
        ("out-slots", "Inconsistencies", "Collected, not fused,\nnot shown in the UI"),
        ("out-state", "Per-claim state", "not_assessed, corroborated,\nsingle-source, contested"),
        ("out-overall", "Overall corroboration", "not_found ≠ out_of_range;\nstill not a verdict"),
    ]
    x = 60
    for key, title, body in cards:
        d.box(key, x, 1168, 292, 120, title, body, fill=PALE_BLUE, title_size=15, body_size=13)
        x += 308

    d.box(
        "gate",
        60,
        1320,
        900,
        120,
        "Journalist reviews this layer, then chooses",
        "Proceed → Layer 5 turns these states into uncertainty and publication risk.\n"
        "Re-run scores the pairs again. Ask can only use this layer’s output.",
        fill=ORANGE,
        title_size=17,
        body_size=15,
    )
    d.box(
        "next",
        996,
        1320,
        360,
        120,
        "Next: Layer 5",
        "Uncertainty and\npublication risk",
        fill=BLUE,
        title_size=17,
        body_size=15,
    )
    d.box(
        "not",
        1388,
        1320,
        492,
        120,
        "This layer does not",
        "Emit a true/false score or an editorial decision. Disagreement is shown, not hidden.",
        fill=RED,
        title_size=17,
        body_size=15,
    )

    d.text(
        "footer",
        60,
        1472,
        "Source of truth: backend/app/layers/evidence.py, backend/app/scoring/corroboration.py, backend/app/engines/nli.py,\n"
        "backend/app/engines/llm_router.py, backend/app/scoring/urls.py (grouping_url), backend/app/retrieval/independence.py,\n"
        "backend/app/schemas/envelope.py (CorroborationPayload, GeminiClaimAnalysis), src/components/layerOutputs.tsx. "
        "Tests: backend/tests/test_evidence_blinding.py, test_evidence_fusion.py, test_nli_engine.py, test_evidence_visibility.py.",
        size=12,
        color="#868e96",
        width=1880,
    )

    d.arrow("a-in-nli-sel", "from-l3", "nli-sel")
    d.arrow("a-in-llm-sel", "from-l3", "llm-sel")
    d.arrow("a-sel-nli", "nli-sel", "nli")
    d.arrow("a-sel-llm", "llm-sel", "llm")
    d.arrow("a-nli-fuse", "nli", "fuse", drop="src")
    d.arrow("a-llm-fuse", "llm", "fuse", drop="src")
    d.arrow("a-fuse-matrix", "fuse", "out-matrix", drop="dst")
    d.arrow("a-matrix-gate", "out-matrix", "gate", drop="src")
    d.arrow("a-gate-next", "gate", "next", src_side="right", dst_side="left")

    return d


def main() -> None:
    build().write(OUT)


if __name__ == "__main__":
    main()
