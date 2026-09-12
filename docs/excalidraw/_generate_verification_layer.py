"""Generate a high-level Excalidraw diagram for Layer 3."""

from pathlib import Path

from _lib import BLUE, GREEN, ORANGE, PALE_BLUE, RED, VIOLET, YELLOW, Diagram

OUT = Path(__file__).with_name("03-verification-layer.excalidraw")


def build() -> Diagram:
    d = Diagram()
    d.header(
        "Layer 3 — Verification Tool Layer",
        "NewsAuth · Thesis B · COMP4092     Search public portals for the same article and for the same kind of event. The planner writes queries only — it does not score truth.",
    )
    d.pipeline_chips(60, 132, active=3)

    d.box(
        "from-l2",
        420,
        200,
        1100,
        96,
        "From Layer 2 — claims, headline, entities, date window",
        "This layer does not re-read the article to judge it. It only turns that structure into searches.",
        fill=PALE_BLUE,
        title_size=18,
        body_size=15,
    )

    d.box(
        "planner",
        60,
        332,
        1880,
        168,
        "Query planner — Claude (then Gemini, then OpenAI; else a deterministic fallback)",
        "Writes four searches from the claims and names. Instructed not to say whether the story is true.\n"
        "• quoted headline — look for the same article\n"
        "• event boolean (names AND event) — look for the same kind of event\n"
        "• fact-check paraphrase — look for a prior ClaimReview\n"
        "• entity names — look up people / organisations / places on Wikipedia",
        fill=YELLOW,
        title_size=18,
        body_size=15,
    )

    d.box(
        "q1",
        60,
        536,
        450,
        248,
        "Question 1 — Does this article exist?",
        "Quoted-title search\nNewsAPI (title field) + Guardian\n\nAsks: is the same piece already on a public news portal?",
        fill=BLUE,
        title_size=16,
        body_size=15,
    )
    d.box(
        "q2",
        530,
        536,
        450,
        248,
        "Question 2 — Is this kind of event reported?",
        "Boolean event query\nNewsAPI + Guardian + GNews / NewsData\n\nAsks: do independent outlets report this type of event, even if the exact article is missing?",
        fill=BLUE,
        title_size=16,
        body_size=15,
    )
    d.box(
        "q3",
        1000,
        536,
        450,
        248,
        "Supporting — prior fact-checks",
        "Google Fact Check Tools\n\nLooks for an existing ClaimReview rating. That rating belongs to the original fact-checker — it is not this system’s verdict.",
        fill=VIOLET,
        title_size=16,
        body_size=15,
    )
    d.box(
        "q4",
        1470,
        536,
        470,
        248,
        "Supporting — entity grounding",
        "Wikipedia, one lookup per person / org / place\n\nA missing page is a coverage gap, not proof the name was invented.",
        fill=VIOLET,
        title_size=16,
        body_size=15,
    )

    d.box(
        "post",
        60,
        860,
        1880,
        168,
        "Collapse the hits into a usable set",
        "Drop duplicate URLs. Rank remaining articles by similarity to the claims; prefer different publisher families.\n"
        "Then classify existence: exact URL match · title match · near-duplicate · syndicate / reprint · not found.\n"
        "“Not found”, empty results, or a skipped API are missing coverage — not evidence the story is fake.",
        fill=GREEN,
        title_size=18,
        body_size=15,
    )

    d.text("out-label", 60, 1060, "What this layer produces", size=16, color="#495057")
    cards = [
        ("out-q", "Planned queries", "Quoted headline, event\nboolean, fact-check, entities"),
        ("out-ev", "Retrieved articles", "Unique, ranked items\nfrom the news portals"),
        ("out-ex", "Existence class", "Same article found,\nnear-duplicate, or not found"),
        ("out-fc", "Prior fact-checks", "Other outlets’ ClaimReview\nratings, if any"),
        ("out-wiki", "Wiki grounding", "Which entities have a\npublic Wikipedia page"),
        ("out-tools", "Tool statuses", "ok / empty / skipped / error\nrecorded, never hidden"),
    ]
    x = 60
    for key, title, body in cards:
        d.box(key, x, 1088, 292, 120, title, body, fill=PALE_BLUE, title_size=15, body_size=13)
        x += 308

    d.box(
        "gate",
        60,
        1248,
        900,
        120,
        "Journalist reviews this layer, then chooses",
        "Proceed → Layer 4 compares each claim against these articles.\n"
        "Re-run searches again. Ask can only use this layer’s output.",
        fill=ORANGE,
        title_size=17,
        body_size=15,
    )
    d.box(
        "next",
        996,
        1248,
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
        1248,
        492,
        120,
        "This layer does not",
        "Score true/false, run NLI, or decide authenticity. Empty portals are uncertainty.",
        fill=RED,
        title_size=17,
        body_size=15,
    )

    d.arrow("a-in-plan", "from-l2", "planner")
    d.arrow("a-p-q1", "planner", "q1", drop="dst")
    d.arrow("a-p-q2", "planner", "q2", drop="dst")
    d.arrow("a-p-q3", "planner", "q3", drop="dst")
    d.arrow("a-p-q4", "planner", "q4", drop="dst")
    d.arrow("a-q1-post", "q1", "post", drop="src")
    d.arrow("a-q2-post", "q2", "post", drop="src")
    d.arrow("a-q3-post", "q3", "post", drop="src")
    d.arrow("a-q4-post", "q4", "post", drop="src")
    d.arrow("a-post-ev", "post", "out-ev")
    d.arrow("a-ev-gate", "out-ev", "gate")
    d.arrow("a-gate-next", "gate", "next", src_side="right", dst_side="left")

    return d


def main() -> None:
    build().write(OUT)


if __name__ == "__main__":
    main()
