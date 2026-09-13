"""Cross-check two independent claim-extraction passes (Layer 2).

Claims are matched by where they sit in the article, not by how they are
worded. Two passes agree when their [span_start, span_end) ranges overlap by
at least half the shorter span. There is deliberately no text-similarity
fallback: paraphrases of the same sentence should match because they point at
the same characters, and two different sentences should not match just because
they read alike.

Agreement here means the two extractors agreed. It never means the claim is
true, corroborated, or important.
"""

from __future__ import annotations

from app.schemas.envelope import Claim, ClaimKind

OVERLAP_THRESHOLD = 0.5
_MEANINGFUL_LABELS = {"fact", "opinion", "unclear"}


def overlap_ratio(a: Claim, b: Claim) -> float:
    """Overlap of two spans as a fraction of the shorter span, else 0.0.

    Ungrounded claims have no span and therefore never match anything.
    """
    if a.span_start is None or a.span_end is None:
        return 0.0
    if b.span_start is None or b.span_end is None:
        return 0.0
    if a.grounding == "not_found" or b.grounding == "not_found":
        return 0.0
    overlap = min(a.span_end, b.span_end) - max(a.span_start, b.span_start)
    if overlap <= 0:
        return 0.0
    shorter = min(a.span_end - a.span_start, b.span_end - b.span_start)
    if shorter <= 0:
        return 0.0
    return overlap / shorter


def spans_agree(a: Claim, b: Claim) -> bool:
    return overlap_ratio(a, b) >= OVERLAP_THRESHOLD


def _match_pairs(pass_a: list[Claim], pass_b: list[Claim]) -> list[tuple[int, int]]:
    """Greedy best-overlap-first pairing, so the result is deterministic."""
    candidates = [
        (overlap_ratio(a, b), i, j)
        for i, a in enumerate(pass_a)
        for j, b in enumerate(pass_b)
        if spans_agree(a, b)
    ]
    candidates.sort(key=lambda row: (-row[0], row[1], row[2]))
    used_a: set[int] = set()
    used_b: set[int] = set()
    pairs: list[tuple[int, int]] = []
    for _ratio, i, j in candidates:
        if i in used_a or j in used_b:
            continue
        used_a.add(i)
        used_b.add(j)
        pairs.append((i, j))
    return pairs


def _resolve_label(a: Claim, b: Claim) -> tuple[ClaimKind, str | None]:
    """Merge two labels. A real disagreement becomes 'unclear', never a winner."""
    a_label = a.kind if a.kind in _MEANINGFUL_LABELS else None
    b_label = b.kind if b.kind in _MEANINGFUL_LABELS else None
    if a_label and b_label and a_label != b_label:
        return "unclear", f"passes disagreed on label ({a_label} vs {b_label}), recorded as unclear"
    return (a_label or b_label or "unspecified"), None  # type: ignore[return-value]


def _merge_pair(a: Claim, b: Claim, *, model_a: str, model_b: str) -> Claim:
    """Keep the better-formed claim: prefer an exact quote, tie-break on pass A."""
    winner = b if (b.grounding == "exact" and a.grounding != "exact") else a
    label, label_note = _resolve_label(a, b)
    merged = winner.model_copy(deep=True)
    merged.kind = label
    merged.agreement = "both"
    merged.variant_texts = [a.text, b.text]
    note = f"both passes ({model_a}, {model_b}) extracted this span"
    if label_note:
        note = f"{note}; {label_note}"
    merged.agreement_note = note
    return merged


def _single_pass_note(claim: Claim, which: str, model: str) -> str:
    if claim.grounding == "not_found":
        return (
            f"only pass {which} ({model}) produced this claim, and its quote is not in "
            "the article, so it cannot be span-matched — lower confidence, not disproved"
        )
    return (
        f"only pass {which} ({model}) extracted this span — lower extraction "
        "confidence, not evidence the claim is wrong"
    )


def _sort_key(claim: Claim) -> tuple[int, int, str]:
    # Document order, with ungrounded claims last so they are easy to find.
    if claim.span_start is None:
        return (1, 0, claim.id)
    return (0, claim.span_start, claim.id)


def reconcile_passes(
    pass_a: list[Claim],
    pass_b: list[Claim],
    *,
    model_a: str,
    model_b: str,
) -> list[Claim]:
    """Merge two passes, keeping every claim either pass produced.

    A claim found by only one pass is kept and labelled, never discarded.
    Returned claims are renumbered c1..cN in document order.
    """
    pairs = _match_pairs(pass_a, pass_b)
    matched_a = {i for i, _ in pairs}
    matched_b = {j for _, j in pairs}

    merged: list[Claim] = [
        _merge_pair(pass_a[i], pass_b[j], model_a=model_a, model_b=model_b) for i, j in pairs
    ]
    for i, claim in enumerate(pass_a):
        if i in matched_a:
            continue
        only = claim.model_copy(deep=True)
        only.agreement = "pass_a_only"
        only.variant_texts = [claim.text]
        only.agreement_note = _single_pass_note(claim, "A", model_a)
        merged.append(only)
    for j, claim in enumerate(pass_b):
        if j in matched_b:
            continue
        only = claim.model_copy(deep=True)
        only.agreement = "pass_b_only"
        only.variant_texts = [claim.text]
        only.agreement_note = _single_pass_note(claim, "B", model_b)
        merged.append(only)

    merged.sort(key=_sort_key)
    for n, claim in enumerate(merged, start=1):
        claim.id = f"c{n}"
    return merged


def mark_single_pass(claims: list[Claim], *, model: str, reason: str) -> list[Claim]:
    """Label claims from a run where no cross-check happened.

    Agreement is set to 'both' so the enum stays meaningful downstream, but
    `passes_independent` will be False and the note says so plainly. Callers
    must not present this as two passes agreeing.
    """
    for n, claim in enumerate(claims, start=1):
        claim.id = f"c{n}"
        claim.agreement = "both"
        claim.variant_texts = [claim.text]
        claim.agreement_note = f"{reason} ({model}); not cross-checked by a second pass"
    return claims


def agreement_rate(claims: list[Claim]) -> float:
    """both / total. Extraction overlap only — not accuracy, not truth."""
    if not claims:
        return 0.0
    both = sum(1 for claim in claims if claim.agreement == "both")
    return round(both / len(claims), 4)
