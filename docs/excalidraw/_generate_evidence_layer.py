"""Generate a high-level Excalidraw diagram for Layer 4."""

from pathlib import Path

from _lib import BLUE, GREEN, ORANGE, PALE_BLUE, RED, VIOLET, YELLOW, Diagram

OUT = Path(__file__).with_name("04-evidence-layer.excalidraw")


def build() -> Diagram:
    d = Diagram()
    d.header(
        "Layer 4 — Evidence Analysis",
        "NewsAuth · Thesis B · COMP4092     Compare each claim against the retrieved articles. Two independent engines, then a deterministic fuse. No authenticity score.",
    )
    d.pipeline_chips(60, 132, active=4)

    d.box(
        "from-l3",
        420,
        200,
        1100,
        96,
        "From Layer 3 — claims × retrieved articles",
        "Atomic claims from Layer 2, plus the ranked snippets, existence class, and publisher families from Layer 3.",
        fill=PALE_BLUE,
        title_size=18,
        body_size=15,
    )

    d.box(
        "split",
        520,
        324,
        900,
        56,
        "Every claim is scored against every snippet — twice, on purpose",
        fill=YELLOW,
        title_size=16,
    )

    d.box(
        "nli",
        60,
        416,
        900,
        340,
        "Engine A — DeBERTa MNLI (non-generative)",
        "Preferred: DeBERTa. If that is down: BART MNLI, then lexical overlap.\n"
        "\n"
        "For each claim × article snippet it returns:\n"
        "entailment · contradiction · neutral, with a confidence.\n"
        "\n"
        "It does not write prose and cannot invent a verdict.\n"
        "If there are no pairs, that is recorded as empty — not as false.",
        fill=BLUE,
        title_size=18,
        body_size=15,
    )

    d.box(
        "llm",
        1020,
        416,
        860,
        340,
        "Engine B — blinded Gemini (then Claude)",
        "Sees only the claims and the evidence list. It is not given DeBERTa labels, the existence class, or a requested verdict.\n"
        "\n"
        "For each claim it lists which source_ids support, refute, or are unrelated, plus slot clashes (date, place, number, actor).\n"
        "\n"
        "Invented source IDs are dropped. If Gemini is down, fusion continues on NLI alone.",
        fill=VIOLET,
        title_size=18,
        body_size=15,
    )

    d.box(
        "fuse",
        60,
        792,
        1880,
        200,
        "Deterministic fusion — a rule, not a third model",
        "Count support and contradiction by publisher family, not by URL (bbc.com and bbc.co.uk are one family).\n"
        "Agreement: convergent · contested · NLI-only · LLM-only · none.\n"
        "Then overlay Layer 3 existence to pick a corroboration state: corroborated coverage · event corroborated · single source · contested reporting · no corroboration found.\n"
        "No true/false probability is produced.",
        fill=GREEN,
        title_size=18,
        body_size=15,
    )

    d.text("out-label", 60, 1024, "What this layer produces", size=16, color="#495057")
    cards = [
        ("out-matrix", "Claim–evidence matrix", "Each cell: NLI label\nplus LLM stance"),
        ("out-agree", "Engine agreement", "convergent, contested,\nor one engine only"),
        ("out-fam", "Independent families", "How many publisher\nfamilies support / contradict"),
        ("out-slots", "Inconsistencies", "Date, place, number, actor\nclashes Gemini noticed"),
        ("out-state", "Per-claim state", "corroborated, single-source,\ncontested, or none found"),
        ("out-overall", "Overall corroboration", "One state for the run —\nstill not a verdict"),
    ]
    x = 60
    for key, title, body in cards:
        d.box(key, x, 1052, 292, 120, title, body, fill=PALE_BLUE, title_size=15, body_size=13)
        x += 308

    d.box(
        "gate",
        60,
        1212,
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
        1212,
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
        1212,
        492,
        120,
        "This layer does not",
        "Emit a true/false score or an editorial decision. Disagreement is shown, not hidden.",
        fill=RED,
        title_size=17,
        body_size=15,
    )

    d.arrow("a-in-split", "from-l3", "split")
    d.arrow("a-split-nli", "split", "nli")
    d.arrow("a-split-llm", "split", "llm")
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
