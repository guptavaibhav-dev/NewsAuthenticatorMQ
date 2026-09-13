"""Generate a high-level Excalidraw diagram for Layer 2."""

from pathlib import Path

from _lib import (
    BLUE,
    GRAY,
    GREEN,
    ORANGE,
    PALE_BLUE,
    RED,
    VIOLET,
    YELLOW,
    Diagram,
)

OUT = Path(__file__).with_name("02-preprocess-layer.excalidraw")


def build() -> Diagram:
    d = Diagram()
    d.header(
        "Layer 2 — Pre-processing and Classification",
        "NewsAuth · Thesis B · COMP4092     Turn the ingested article into structure: claims, entities, and a date window. Claims are extracted twice and cross-checked. Nothing here decides if the story is true.",
    )
    d.pipeline_chips(60, 132, active=2)

    d.box(
        "from-l1",
        420,
        200,
        1100,
        96,
        "From Layer 1 — the ingested article",
        "The raw body, plus any fetched headline, URL, and publisher domain. That is all this layer reads.",
        fill=PALE_BLUE,
        title_size=18,
        body_size=15,
    )

    d.box(
        "split",
        620,
        324,
        700,
        56,
        "The same text is read three times, on purpose",
        fill=YELLOW,
        title_size=16,
    )

    d.box(
        "pass-a",
        60,
        420,
        580,
        300,
        "Pass A — claim extraction",
        "Preferred model (GPT-4.1), temperature 0. Falls back to Claude,\n"
        "then Gemini, if the preferred model is down.\n"
        "\n"
        "Extracts, from the article alone:\n"
        "• content type and headline\n"
        "• atomic check-worthy claims, labelled c1, c2, …\n"
        "• for each claim, a source_quote copied character for character\n"
        "• label: fact, opinion, or unclear\n"
        "• people, organisations, places, dates\n"
        "• a date window for later search\n"
        "\n"
        "A claim with no verbatim supporting quote must be omitted rather\n"
        "than invented. Told not to judge whether the story is true.",
        fill=BLUE,
        title_size=17,
        body_size=14,
    )

    d.box(
        "pass-b",
        672,
        420,
        580,
        300,
        "Pass B — independent re-extraction",
        "A different model when one is configured (Claude, else Gemini),\n"
        "also at temperature 0. Same contract, independently worded prompt.\n"
        "\n"
        "It never sees Pass A’s output. Both passes run at the same time.\n"
        "\n"
        "If only one provider is configured, both passes run on it and\n"
        "passes_independent is recorded as false — so nothing downstream\n"
        "reads the overlap as a genuine cross-check.\n"
        "\n"
        "Switchable: CLAIM_PASSES = 1 turns the second pass off.\n"
        "With no model at all, long sentences become claims instead.",
        fill=BLUE,
        title_size=17,
        body_size=14,
    )

    d.box(
        "ner",
        1284,
        420,
        596,
        300,
        "Engine B — independent NER",
        "A different engine from the LLM. It does not see the LLM’s answers.\n"
        "\n"
        "Tries, in order:\n"
        "1. Hugging Face token classifier\n"
        "2. spaCy\n"
        "3. simple name and date patterns\n"
        "\n"
        "Finds mentions of:\n"
        "people · organisations · places · dates · events\n"
        "\n"
        "This second look exists so one model cannot quietly invent or\n"
        "drop names.",
        fill=VIOLET,
        title_size=17,
        body_size=14,
    )

    d.box(
        "ground",
        60,
        770,
        1180,
        228,
        "Ground every claim from both passes back to the article — done in code, not by the model",
        "The model is not trusted to have quoted accurately. Each source_quote is located in raw_text here:\n"
        "exact substring first; if that fails, one retry comparing normalised forms of both strings "
        "(NFKC · whitespace runs collapsed to one space · curly quotes and dashes folded to ASCII).\n"
        "There is no fuzzy or approximate matching. A near-miss is recorded as a failure.\n"
        "\n"
        "Each claim then carries span_start / span_end into raw_text, grounding = exact | normalised | not_found, "
        "and which Layer 1 segment the span sits in (pasted / fetched / spans_both).\n"
        "A not_found quote does not appear in the article and was most likely invented. That claim is kept, "
        "counted in ungrounded_claim_count, and shown to the journalist as unverified — never quietly dropped.",
        fill=YELLOW,
        title_size=17,
        body_size=15,
    )

    d.box(
        "crosscheck",
        60,
        1038,
        1180,
        304,
        "Cross-check the two passes — matched by span, never by wording",
        "Two claims are the same claim when their [span_start, span_end) ranges overlap by at least half the shorter "
        "span. Wording is never compared: two paraphrases of one sentence match because they point at the same "
        "characters, and two different sentences do not match just because they read alike.\n"
        "\n"
        "Found by both passes → agreement = “both”, and both wordings are kept in variant_texts. Found by one pass "
        "only → “pass_a_only” or “pass_b_only”: kept and labelled lower-confidence, never discarded.\n"
        "\n"
        "If the two passes disagree on the label, the claim is recorded as unclear with the reason. No winner is picked.\n"
        "\n"
        "An ungrounded (not_found) claim has no span, so it cannot be matched — single-pass by definition.\n"
        "\n"
        "The layer records claim_agreement_rate (both / total) and passes_independent. Agreement means the two "
        "extractors agreed. It does not mean the claim is true, and no later layer may read it as a truth signal.",
        fill=GREEN,
        title_size=17,
        body_size=15,
    )

    d.box(
        "merge",
        60,
        1382,
        1820,
        140,
        "Reconcile — keep both answers visible",
        "Claims come from the two passes above (or the sentence fallback when no model is available).\n"
        "Entities are combined. A name both engines saw is tagged “both”.\n"
        "A name only one engine saw is kept, and listed as a disagreement — not discarded.\n"
        "Date window: use the LLM’s window; otherwise ±2 days around a date found in the text.",
        fill=GREEN,
        title_size=18,
        body_size=15,
    )

    d.text("out-label", 60, 1558, "What this layer produces", size=16, color="#495057")
    cards = [
        ("out-type", "Content type", "article, claim, headline,\nsocial post, or mixed"),
        ("out-head", "Headline", "From the LLM, or the\nheadline fetched in Layer 1"),
        ("out-claims", "Atomic claims", "c1, c2, … with source quote,\noffsets, grounding, label,\nand agreement: both /\npass A only / pass B only"),
        ("out-ents", "Entities", "People, organisations,\nplaces, dates — tagged\nllm / ner / both"),
        ("out-dates", "Date window", "start → end\nwith high / weak / none"),
        ("out-dis", "Disagreements", "LLM-only vs NER-only names,\nungrounded_claim_count, and\nclaim_agreement_rate"),
    ]
    x = 60
    for key, title, body in cards:
        d.box(key, x, 1586, 292, 140, title, body, fill=PALE_BLUE, title_size=15, body_size=13)
        x += 308

    d.box(
        "gate",
        60,
        1766,
        900,
        140,
        "Journalist reviews this layer, then chooses",
        "Proceed → Layer 3 searches news and fact-check portals using these claims.\n"
        "Re-run extracts claims again. Ask can only use this layer’s output.\n"
        "Claims flagged unverified, or found by only one pass, are visible here first.",
        fill=ORANGE,
        title_size=17,
        body_size=15,
    )
    d.box(
        "next",
        996,
        1766,
        360,
        140,
        "Next: Layer 3",
        "Verification tools\n(query planner + news APIs)",
        fill=BLUE,
        title_size=17,
        body_size=15,
    )
    d.box(
        "not",
        1388,
        1766,
        492,
        140,
        "This layer does not",
        "Search the web, compare outlets,\nor decide authentic / fake.\nGrounding proves a passage exists;\nagreement proves two extractors\nmatched. Neither means it is true.",
        fill=RED,
        title_size=17,
        body_size=15,
    )

    d.arrow("a-in-split", "from-l1", "split")
    d.arrow("a-split-pass-a", "split", "pass-a")
    d.arrow("a-split-pass-b", "split", "pass-b")
    d.arrow("a-split-ner", "split", "ner")
    d.arrow("a-pass-a-ground", "pass-a", "ground")
    d.arrow("a-pass-b-ground", "pass-b", "ground")
    d.arrow("a-ground-cross", "ground", "crosscheck")
    d.arrow("a-cross-merge", "crosscheck", "merge")
    d.arrow("a-ner-merge", "ner", "merge", drop=True)
    d.arrow("a-merge-claims", "merge", "out-claims")
    d.arrow("a-claims-gate", "out-claims", "gate")
    d.arrow("a-gate-next", "gate", "next", src_side="right", dst_side="left")

    d.text(
        "footer",
        60,
        1946,
        "Source of truth: backend/app/layers/preprocess.py, backend/app/layers/grounding.py, backend/app/layers/claim_agreement.py,\n"
        "backend/app/engines/ner.py, backend/app/config.py (CLAIM_PASSES), backend/app/schemas/envelope.py (Claim, ClassificationPayload), "
        "src/components/layerOutputs.tsx. Tests: backend/tests/test_claim_grounding.py, backend/tests/test_claim_agreement.py.",
        size=12,
        color="#868e96",
        width=1880,
    )

    return d


def main() -> None:
    build().write(OUT)


if __name__ == "__main__":
    main()
