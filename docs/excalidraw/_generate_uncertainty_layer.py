"""Generate a high-level Excalidraw diagram for Layer 5."""

from pathlib import Path

from _lib import BLUE, GREEN, ORANGE, PALE_BLUE, RED, VIOLET, YELLOW, Diagram

OUT = Path(__file__).with_name("05-uncertainty-layer.excalidraw")


def build() -> Diagram:
    d = Diagram()
    d.header(
        "Layer 5 — Uncertainty and Risk Assessment",
        "NewsAuth · Thesis B · COMP4092     Name what is unknown and put a publication-risk band on the run. Deterministic rules first, a blinded model second. Still a recommendation, never a verdict.",
    )
    d.pipeline_chips(60, 132, active=5)

    d.box(
        "from-l4",
        420,
        200,
        1100,
        96,
        "From Layer 4 — structured scores, not prose",
        "Existence class, per-claim corroboration states and engine agreement, independent publisher families, tool statuses, missing Wikipedia hits, entity disagreements, fetch status.",
        fill=PALE_BLUE,
        title_size=18,
        body_size=15,
    )

    d.box(
        "blind",
        520,
        324,
        900,
        56,
        "The model is blinded — structured signals only, no analyst prose, no target verdict",
        fill=YELLOW,
        title_size=16,
    )

    d.box(
        "rules",
        60,
        416,
        900,
        340,
        "Baseline — deterministic rules, always run first",
        "Every gap in the run becomes a sentence. Skipped or failed tools, an existence class of not found, a Wikipedia miss, or a failed URL fetch are collected as unknowns.\n"
        "\n"
        "Fewer than two independent publisher families, a claim where NLI and Gemini disagree, or clashing entity sets are collected as weak-evidence flags.\n"
        "\n"
        "The corroboration state then picks a conservative risk band and recommended label. This payload exists before any model is contacted.",
        fill=BLUE,
        title_size=18,
        body_size=15,
    )

    d.box(
        "model",
        1020,
        416,
        860,
        340,
        "Then a model, only if a provider is ready",
        "Tried in order: OpenAI, then Anthropic, then Gemini. The first provider that answers is used.\n"
        "\n"
        "It receives the structured signals with an explicit instruction that missing tools do not imply fabrication.\n"
        "\n"
        "It is told it may not declare the story true or false. It returns unknowns, weak evidence, an independence note, a risk band, a recommended label, and a short rationale.\n"
        "\n"
        "If no provider is configured, or the call or the parse fails, the baseline simply stands.",
        fill=VIOLET,
        title_size=18,
        body_size=15,
    )

    d.box(
        "validate",
        60,
        792,
        1880,
        168,
        "Validation and fallback — the rules keep the last word",
        "Risk must be one of low · moderate · high · unknown, and the label must be one of the six newsroom labels. Anything else is discarded and the rule-based value is kept.\n"
        "Empty lists coming back from the model fall back to the rule-based unknowns and weak-evidence flags, so this layer can never return silently empty.\n"
        "Whichever engine actually produced the payload is recorded on the envelope — “rule-based” when the model was skipped, failed, or rejected.",
        fill=GREEN,
        title_size=18,
        body_size=15,
    )

    d.text(
        "map-label",
        60,
        992,
        "How the corroboration state becomes the conservative default",
        size=16,
        color="#495057",
    )
    mapping = [
        (
            "map-corrob",
            "corroborated coverage · event corroborated",
            "Recommend verified, publication risk low.",
        ),
        (
            "map-single",
            "single source",
            "Recommend needs investigation, publication risk moderate.",
        ),
        (
            "map-contested",
            "contested reporting",
            "Recommend needs investigation, publication risk high.",
        ),
        (
            "map-none",
            "no corroboration found",
            "Recommend unverifiable, publication risk high. Absence of hits is treated as uncertainty, not as proof of a hoax.",
        ),
    ]
    x = 60
    for key, title, body in mapping:
        d.box(key, x, 1020, 452, 110, title, body, fill=PALE_BLUE, title_size=15, body_size=13)
        x += 476

    d.text("out-label", 60, 1166, "What this layer produces", size=16, color="#495057")
    cards = [
        ("out-unknowns", "Unknowns", "Every gap the run hit,\nwritten as plain sentences"),
        ("out-weak", "Weak-evidence flags", "Where corroboration is\nthin or contested"),
        ("out-indep", "Independence note", "How many publisher families,\nplus the unknown-band caveat"),
        ("out-risk", "Publication risk", "low · moderate · high\n· unknown"),
        ("out-rec", "Recommended label", "One of the six labels —\na suggestion, not a verdict"),
        ("out-engine", "Engine recorded", "openai, anthropic, gemini,\nor rule-based"),
    ]
    x = 60
    for key, title, body in cards:
        d.box(key, x, 1194, 292, 120, title, body, fill=PALE_BLUE, title_size=15, body_size=13)
        x += 308

    d.box(
        "gate",
        60,
        1354,
        900,
        120,
        "Journalist reviews this layer, then chooses",
        "Proceed → Layer 6, where a human records the newsroom decision.\n"
        "Re-run assesses the same signals again. Ask can only use this layer’s output.",
        fill=ORANGE,
        title_size=17,
        body_size=15,
    )
    d.box(
        "next",
        996,
        1354,
        360,
        120,
        "Next: Layer 6",
        "Human editorial\ndecision",
        fill=BLUE,
        title_size=17,
        body_size=15,
    )
    d.box(
        "not",
        1388,
        1354,
        492,
        120,
        "This layer does not",
        "Score authenticity, commit its own recommendation, or read a missing tool as evidence of fakery.",
        fill=RED,
        title_size=17,
        body_size=15,
    )

    d.arrow("a-in-blind", "from-l4", "blind")
    d.arrow("a-blind-rules", "blind", "rules")
    d.arrow("a-blind-model", "blind", "model")
    d.arrow("a-rules-val", "rules", "validate", drop="src")
    d.arrow("a-model-val", "model", "validate", drop="src")
    d.arrow("a-val-map", "validate", "map-corrob", drop="dst")
    d.arrow("a-map-out", "map-corrob", "out-unknowns", drop="src")
    d.arrow("a-out-gate", "out-unknowns", "gate", drop="src")
    d.arrow("a-gate-next", "gate", "next", src_side="right", dst_side="left")

    return d


def main() -> None:
    build().write(OUT)


if __name__ == "__main__":
    main()
