"""Ordering retrieved pages by similarity to the claims we searched for.

Ranking is ordering and nothing else. `relevance_score` measures textual
similarity between a claim and a page's title and lead — it does not measure
whether the page agrees with the claim, whether the claim is true, or whether
the publisher is any good. A page that flatly contradicts a claim scores high,
because it is about the same thing. Reading these scores as support would
invert the layer's meaning.

The engine behind them is recorded for the same reason. `EmbeddingEngine` uses
Hugging Face when a token is configured and silently falls back to local
character-trigram cosine when it is not, and the two produce numbers on
unrelated scales. A run that degraded to the fallback must say so, or its scores
will later be compared against thresholds that were never tuned for them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from app.engines.embeddings import cosine_dense
from app.schemas.retrieval import SearchHit

# ---------------------------------------------------------------------------
# Thresholds inherited from the old Layer 3.
#
# BOTH NUMBERS WERE TUNED AGAINST CHAR-TRIGRAM COSINE AND DO NOT TRANSFER TO
# SEMANTIC EMBEDDINGS. Trigram cosine measures surface string overlap, so two
# unrelated news sentences sit near 0.1-0.2 and 0.22 is a meaningful floor.
# Sentence embeddings put almost any two English news sentences well above 0.5,
# where 0.22 admits everything and 0.88 rejects genuine reprints that were
# reworded. Carrying either constant across engines is a known open question,
# not a settled value — which is why `ranking_method` is recorded alongside
# every score, and why nothing in this module applies a threshold silently.
#
# Comparing scores from ONE method across runs is now sound: the char-ngram
# fallback's trigram buckets were salted per process until stage 5, so the same
# article scored differently after every restart. Across methods, still not.
# ---------------------------------------------------------------------------
RELEVANCE_FLOOR = 0.22
NEAR_DUPLICATE_THRESHOLD = 0.88

#: engine_name prefix -> the ranking_method label recorded in RetrievalPayload.
_EMBEDDING_PREFIX = "hf:"


@dataclass
class Ranking:
    """Ranked hits, plus which engine actually produced the numbers."""

    hits: list[SearchHit] = field(default_factory=list)
    ranking_method: str = ""
    ranking_engine_name: str = ""


def ranking_method_for(engine_name: Any) -> str:
    """Label the scale the scores are on, not the engine's brand name.

    Two labels, because there are two incomparable scales. Anything unexpected
    is reported verbatim rather than mapped onto one of them — mislabelling the
    scale is worse than admitting we do not recognise it.
    """
    name = engine_name if isinstance(engine_name, str) else ""
    if name.startswith(_EMBEDDING_PREFIX):
        return "embedding"
    if "ngram" in name or "trigram" in name:
        return "char-ngram"
    return name


def _hit_text(hit: SearchHit) -> str:
    return f"{hit.title} {hit.snippet or ''}".strip()


def _claim_text(claim: Any) -> str:
    text = getattr(claim, "text", None)
    return text.strip() if isinstance(text, str) else ""


async def rank(
    hits: Iterable[SearchHit],
    claims: Iterable[Any],
    embeddings: Any,
) -> Ranking:
    """Score each hit against the claims, and order by that score.

    A hit retrieved for a specific claim is scored against that claim; one from
    an existence or entity query is scored against its best match among all
    claims, since it was never tied to one. Scores are left at None when there
    is nothing to compare against, rather than defaulting to zero — an unscored
    page is unranked, not irrelevant.
    """
    rows = [hit for hit in hits if isinstance(hit, SearchHit)]
    claim_rows = [claim for claim in (claims or ()) if _claim_text(claim)]
    if not rows or not claim_rows:
        # Nothing was ranked, so no method is claimed. Leaving these blank is
        # what tells a reader the ordering below is arbitrary.
        return Ranking(hits=rows, ranking_method="", ranking_engine_name="")

    claim_texts = [_claim_text(claim) for claim in claim_rows]
    hit_texts = [_hit_text(hit) for hit in rows]

    try:
        vectors = await embeddings.embed(claim_texts + hit_texts)
    except Exception:
        # Ranking is a convenience; losing it must not lose the retrieval.
        return Ranking(hits=rows, ranking_method="", ranking_engine_name="")

    if len(vectors) != len(claim_texts) + len(hit_texts):
        return Ranking(hits=rows, ranking_method="", ranking_engine_name="")

    claim_vectors = vectors[: len(claim_texts)]
    hit_vectors = vectors[len(claim_texts) :]
    by_claim_id = {
        getattr(claim, "id", None): index for index, claim in enumerate(claim_rows)
    }

    scored: list[SearchHit] = []
    for hit, vector in zip(rows, hit_vectors):
        index = by_claim_id.get(hit.claim_id)
        if index is not None:
            score = cosine_dense(claim_vectors[index], vector)
        else:
            score = max(
                (cosine_dense(claim_vector, vector) for claim_vector in claim_vectors),
                default=0.0,
            )
        scored.append(hit.model_copy(update={"relevance_score": round(float(score), 6)}))

    engine_name = getattr(embeddings, "engine_name", "") or ""
    # Sorted highest first, with canonical_url breaking ties so that two pages
    # scoring identically always come back in the same order.
    scored.sort(key=lambda hit: (-(hit.relevance_score or 0.0), hit.canonical_url))
    return Ranking(
        hits=scored,
        ranking_method=ranking_method_for(engine_name),
        ranking_engine_name=engine_name,
    )
