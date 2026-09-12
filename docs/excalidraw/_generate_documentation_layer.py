"""Generate a high-level Excalidraw diagram for Layer 7."""

from pathlib import Path

from _lib import BLUE, GREEN, ORANGE, PALE_BLUE, RED, VIOLET, YELLOW, Diagram

OUT = Path(__file__).with_name("07-documentation-layer.excalidraw")


def build() -> Diagram:
    d = Diagram()
    d.header(
        "Layer 7 — Output and Documentation",
        "NewsAuth · Thesis B · COMP4092     Write a citation-backed audit record of the run. Not a verdict. The journalist’s Layer 6 label is already on the envelope.",
    )
    d.pipeline_chips(60, 132, active=7)

    d.box(
        "from-l6",
        420,
        200,
        1100,
        96,
        "From Layer 6 — the journalist has already chosen",
        "The full envelope is in: claims, sources, corroboration, uncertainty, and the human decision. This layer records that work. It does not reopen the verdict.",
        fill=PALE_BLUE,
        title_size=18,
        body_size=15,
    )

    d.box(
        "start",
        420,
        324,
        1100,
        56,
        "Starts immediately after Confirm. There is no second Proceed.",
        fill=YELLOW,
        title_size=16,
    )

    d.box(
        "template",
        60,
        416,
        900,
        300,
        "Always first — a deterministic template",
        "Filled from the envelope, no model required:\n"
        "• claims listed by id\n"
        "• retrieved outlets, or “no portal hits ≠ falsity”\n"
        "• existence class, corroboration state, family count\n"
        "• per-claim NLI / Gemini agreement\n"
        "• uncertainty rationale and unknowns\n"
        "• citations (article URLs + fact-check URLs)\n"
        "\n"
        "This template is the fallback if every LLM is down.",
        fill=BLUE,
        title_size=18,
        body_size=15,
    )

    d.box(
        "llm",
        1020,
        416,
        860,
        300,
        "Then a writer — Claude (then Gemini, then OpenAI)",
        "Rewrites the template as short, citation-backed prose. Instructed: do not issue a truth verdict.\n"
        "\n"
        "Cite evidence by outlet and URL. Keep each section to 1–3 paragraphs.\n"
        "\n"
        "If Claude is down, Gemini then OpenAI try. If all fail, the template stands and the failure is traced.",
        fill=VIOLET,
        title_size=18,
        body_size=15,
    )

    d.box(
        "caveat",
        60,
        752,
        1880,
        88,
        "Every record carries a fixed caveat",
        "“Decision support only. This record is not an authenticity verdict. Final judgement remains with the journalist.” That sentence is not generated — it is on the schema.",
        fill=YELLOW,
        title_size=17,
        body_size=15,
    )

    d.text("out-label", 60, 868, "What the verification record contains", size=16, color="#495057")
    cards = [
        ("out-claims", "Claims", "What was being checked\n(c1, c2, …)"),
        ("out-src", "Sources", "Which outlets were\nretrieved, and their band"),
        ("out-ev", "Evidence", "Existence class and\noverall corroboration"),
        ("out-cross", "Cross-source", "Per-claim NLI vs LLM\nand prior fact-checks"),
        ("out-unc", "Uncertainty", "Rationale, unknowns,\npublication risk"),
        ("out-rec", "Recommendation", "System label, plus the\njournalist’s recorded choice"),
    ]
    x = 60
    for key, title, body in cards:
        d.box(key, x, 896, 292, 120, title, body, fill=PALE_BLUE, title_size=15, body_size=13)
        x += 308

    d.box(
        "done",
        60,
        1052,
        900,
        168,
        "The run is complete",
        "phase = complete. The inspector shows the record. “View verification summary” opens the full audit: claims, matrix, uncertainty, and this write-up.\n"
        "No further layer will run.",
        fill=GREEN,
        title_size=18,
        body_size=15,
    )
    d.box(
        "keep",
        996,
        1052,
        884,
        168,
        "What is not rewritten",
        "The journalist’s label and notes stay as recorded in Layer 6.\n"
        "Corroboration states and NLI scores are quoted, not recalculated.\n"
        "Citations must come from retrieved URLs — the writer is not to invent sources.",
        fill=GREEN,
        title_size=18,
        body_size=15,
    )

    d.box(
        "gate",
        60,
        1256,
        900,
        120,
        "End of the pipeline",
        "Decision support only. The journalist already judged.\n"
        "This layer leaves an audit trail they can keep with the story.",
        fill=ORANGE,
        title_size=17,
        body_size=15,
    )
    d.box(
        "next",
        996,
        1256,
        360,
        120,
        "No next layer",
        "The seven-layer run\nis finished.",
        fill=BLUE,
        title_size=17,
        body_size=15,
    )
    d.box(
        "not",
        1388,
        1256,
        492,
        120,
        "This layer does not",
        "Issue a true/false verdict, overwrite the human decision, or invent citations.",
        fill=RED,
        title_size=17,
        body_size=15,
    )

    d.arrow("a-in-start", "from-l6", "start")
    d.arrow("a-start-tpl", "start", "template")
    d.arrow("a-start-llm", "start", "llm")
    d.arrow("a-tpl-cav", "template", "caveat", drop="src")
    d.arrow("a-llm-cav", "llm", "caveat", drop="src")
    d.arrow("a-cav-ev", "caveat", "out-ev", drop="dst")
    d.arrow("a-ev-done", "out-ev", "done", drop="src")
    d.arrow("a-done-keep", "done", "keep", src_side="right", dst_side="left")
    d.arrow("a-done-gate", "done", "gate", drop="src")

    return d


def main() -> None:
    build().write(OUT)


if __name__ == "__main__":
    main()
