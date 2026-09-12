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
        "NewsAuth · Thesis B · COMP4092     Turn the ingested article into structure: claims, entities, and a date window. Two independent engines. Neither decides if the story is true.",
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
        "The same text is read twice, on purpose",
        fill=YELLOW,
        title_size=16,
    )

    d.box(
        "llm",
        60,
        420,
        900,
        340,
        "Engine A — LLM classifier",
        "Preferred: GPT-4.1. If that is down: Claude, then Gemini.\n"
        "\n"
        "Reads the article and extracts:\n"
        "• content type (article, claim, headline, social post)\n"
        "• headline\n"
        "• atomic check-worthy claims, labelled c1, c2, …\n"
        "• fact vs opinion\n"
        "• a first pass at people, organisations, places, dates\n"
        "• a date window for later search\n"
        "\n"
        "Told not to judge whether the story is true.\n"
        "If no LLM is available, long sentences become claims.",
        fill=BLUE,
        title_size=18,
        body_size=15,
    )

    d.box(
        "ner",
        1020,
        420,
        860,
        340,
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
        "This second look exists so one model cannot quietly invent or drop names.",
        fill=VIOLET,
        title_size=18,
        body_size=15,
    )

    d.box(
        "merge",
        300,
        800,
        1340,
        200,
        "Reconcile — keep both answers visible",
        "Claims come from the LLM (or the sentence fallback).\n"
        "Entities are combined. A name both engines saw is tagged “both”.\n"
        "A name only one engine saw is kept, and listed as a disagreement — not discarded.\n"
        "Date window: use the LLM’s window; otherwise ±2 days around a date found in the text.",
        fill=GREEN,
        title_size=18,
        body_size=15,
    )

    d.text("out-label", 60, 1036, "What this layer produces", size=16, color="#495057")
    cards = [
        ("out-type", "Content type", "article, claim, headline,\nsocial post, or mixed"),
        ("out-head", "Headline", "From the LLM, or the\nheadline fetched in Layer 1"),
        ("out-claims", "Atomic claims", "c1, c2, … each marked\nfact or opinion"),
        ("out-ents", "Entities", "People, organisations,\nplaces, dates — tagged\nllm / ner / both"),
        ("out-dates", "Date window", "start → end\nwith high / weak / none"),
        ("out-dis", "Disagreements", "LLM-only vs NER-only\nnames, shown to the journalist"),
    ]
    x = 60
    for key, title, body in cards:
        d.box(key, x, 1064, 292, 120, title, body, fill=PALE_BLUE, title_size=15, body_size=13)
        x += 308

    d.box(
        "gate",
        60,
        1224,
        900,
        120,
        "Journalist reviews this layer, then chooses",
        "Proceed → Layer 3 searches news and fact-check portals using these claims.\n"
        "Re-run extracts claims again. Ask can only use this layer’s output.",
        fill=ORANGE,
        title_size=17,
        body_size=15,
    )
    d.box(
        "next",
        996,
        1224,
        360,
        120,
        "Next: Layer 3",
        "Verification tools\n(query planner + news APIs)",
        fill=BLUE,
        title_size=17,
        body_size=15,
    )
    d.box(
        "not",
        1388,
        1224,
        492,
        120,
        "This layer does not",
        "Search the web, compare outlets,\nor decide authentic / fake.",
        fill=RED,
        title_size=17,
        body_size=15,
    )

    d.arrow("a-in-split", "from-l1", "split")
    d.arrow("a-split-llm", "split", "llm")
    d.arrow("a-split-ner", "split", "ner")
    d.arrow("a-llm-merge", "llm", "merge")
    d.arrow("a-ner-merge", "ner", "merge")
    d.arrow("a-merge-claims", "merge", "out-claims")
    d.arrow("a-claims-gate", "out-claims", "gate")
    d.arrow("a-gate-next", "gate", "next", src_side="right", dst_side="left")

    return d


def main() -> None:
    build().write(OUT)


if __name__ == "__main__":
    main()
