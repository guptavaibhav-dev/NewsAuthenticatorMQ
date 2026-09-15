from __future__ import annotations

from datetime import datetime

from app.config import Settings
from app.engines.llm_router import LLMRouter
from app.engines.nli import NliEngine
from app.schemas.envelope import (
    GeminiClaimAnalysis,
    Inconsistency,
    PairAnalysis,
    RunEnvelope,
    Stance,
)
from app.scoring.corroboration import build_payload, fuse_claim
from app.retrieval.run import evidence_source_id
from app.scoring.source_independence import independent_family_count, publisher_family
from app.scoring.urls import canonical_url
from app.logutil import short_error

GEMINI_SYSTEM = """You are Engine B of the Evidence Analysis Layer in a journalist-centred authentication framework.
Compare claims against retrieved evidence items. Cite evidence by source_id only.
You are not given NLI labels, existence class, or a requested verdict. Do not say the story is true or fake.
Return JSON:
{
  "claims": [
    {
      "claim_id": "c1",
      "supported_by": ["id"],
      "contradicted_by": ["id"],
      "unrelated": ["id"],
      "inconsistencies": [{"slot":"date|place|number|actor|other","summary":"...","source_ids":["id"]}],
      "missing_slots": ["..."]
    }
  ]
}
Only use source_ids from the provided evidence list. If unsure, use unrelated.
"""


async def run_evidence(
    envelope: RunEnvelope,
    *,
    settings: Settings,
    nli: NliEngine,
    llm: LLMRouter,
    emit,
) -> None:
    claims = [c for c in envelope.classification.claims if c.checkworthy] or envelope.classification.claims
    evidence = envelope.evidence_items
    evidence_by_id = {item.source_id: item.url for item in evidence}
    source_groups = independent_source_groups(envelope)

    pairs: list[PairAnalysis] = []
    if claims and evidence:
        await emit(
            layer="evidence",
            parameter="claim×evidence",
            process="DeBERTa MNLI stance",
            tool=settings.nli_model,
            status="running",
            detail=f"{len(claims)} claims × {len(evidence)} snippets (non-generative).",
        )
        nli_inputs: list[tuple[str, str, str, str]] = []
        for claim in claims:
            for item in evidence:
                nli_inputs.append((claim.id, item.source_id, item.snippet or item.title, claim.text))
        scored = await nli.score_pairs([(p, h) for _, _, p, h in nli_inputs])
        if nli.engine_name.startswith("lexical"):
            await emit(
                layer="evidence",
                parameter="claim×evidence",
                process="DeBERTa MNLI stance",
                tool=nli.engine_name,
                status="skipped",
                detail=(
                    "Hugging Face NLI unavailable"
                    + (f" ({nli.last_error})" if nli.last_error else "")
                    + "; using lexical overlap fallback."
                ),
            )
        else:
            await emit(
                layer="evidence",
                parameter="claim×evidence",
                process="DeBERTa MNLI stance",
                tool=nli.engine_name,
                status="ok",
                detail=f"Scored {len(scored)} pairs with {nli.engine_name}.",
            )
        for (claim_id, source_id, _, _), (label, score, probs) in zip(nli_inputs, scored):
            item = next(e for e in evidence if e.source_id == source_id)
            pairs.append(
                PairAnalysis(
                    claim_id=claim_id,
                    source_id=source_id,
                    nli_label=label,
                    nli_score=score,
                    nli_probs=probs,
                    independence=_independent(envelope, item.url),
                    temporal_relation=_temporal(envelope.input.fetch_timestamp, item.published_at),
                )
            )
            await emit(
                layer="evidence",
                parameter=f"claim[{claim_id}]",
                process=f"NLI vs {item.outlet}",
                tool=nli.engine_name if nli.engine_name.startswith("hf:") else "lexical-nli",
                status="ok",
                detail=f"{label} ({score:.2f}) — {item.title[:80]}",
            )
    else:
        await emit(
            layer="evidence",
            parameter="claim×evidence",
            process="DeBERTa MNLI stance",
            tool=settings.nli_model,
            status="empty",
            detail="No claim/evidence pairs to score. Absence is not falsity.",
        )

    envelope.analysis = pairs
    envelope.engines_used["nli"] = nli.engine_name

    gemini_rows: list[GeminiClaimAnalysis] = []
    analyst_model = "skipped"
    analyst_attempts = [
        ("gemini", settings.evidence_llm_model),
        ("anthropic", settings.documentation_model),
    ]
    if claims and evidence and any(llm.provider_ready(p) for p, _ in analyst_attempts):
        await emit(
            layer="evidence",
            parameter="claims",
            process="blinded multi-document analysis",
            tool=settings.evidence_llm_model,
            status="running",
            detail="Analyst does not receive DeBERTa labels or an authenticity target.",
        )
        try:
            gemini_rows, provider, analyst_model = await _blinded_analyse(
                envelope, llm, analyst_attempts
            )
            await emit(
                layer="evidence",
                parameter="claims",
                process="blinded multi-document analysis",
                tool=analyst_model,
                status="ok",
                detail=(
                    f"{provider}/{analyst_model} structured stance for {len(gemini_rows)} claim(s); "
                    "hallucinated IDs will be dropped."
                ),
            )
        except Exception as exc:
            analyst_model = "skipped"
            await emit(
                layer="evidence",
                parameter="claims",
                process="blinded multi-document analysis",
                tool=settings.evidence_llm_model,
                status="skipped",
                detail=f"Analyst LLM failed ({short_error(exc)}); fusion will use NLI only.",
            )
    else:
        await emit(
            layer="evidence",
            parameter="claims",
            process="blinded multi-document analysis",
            tool=settings.evidence_llm_model,
            status="skipped",
            detail="Analyst LLM unavailable or no evidence; fusion will use NLI only.",
        )

    envelope.gemini_analysis = gemini_rows
    envelope.engines_used["evidence_llm"] = analyst_model if gemini_rows else "skipped"

    gemini_by_claim = {row.claim_id: row for row in gemini_rows}
    fused = []
    for claim in claims:
        fused.append(
            fuse_claim(
                claim_id=claim.id,
                pairs=[p for p in pairs if p.claim_id == claim.id],
                gemini=gemini_by_claim.get(claim.id),
                evidence_by_id=evidence_by_id,
                threshold=settings.nli_threshold,
                existence=envelope.corroboration.existence,
                source_groups=source_groups,
            )
        )

    envelope.corroboration = build_payload(
        existence=envelope.corroboration.existence,
        claims=fused,
        fact_checks=envelope.corroboration.fact_checks,
        # Layer 3's count, which has already collapsed wire syndication, shared
        # ownership and reprints. MUST NOT be `len(evidence)` or
        # `retrieval.document_count`: those are page counts, and syndication
        # inflates them without adding a single extra newsroom. This is the
        # number the journalist reads as corroboration, so it has to be the
        # number of genuinely separate sources.
        independent_source_count=_independent_source_count(envelope, evidence),
        retrieved=bool(evidence),
    )
    await emit(
        layer="evidence",
        parameter="corroboration",
        process="deterministic fusion",
        tool="fusion",
        status="ok",
        detail=f"overall={envelope.corroboration.overall_state}; no authenticity score assigned.",
    )


async def _blinded_analyse(
    envelope: RunEnvelope,
    llm: LLMRouter,
    attempts: list[tuple[str, str]],
) -> tuple[list[GeminiClaimAnalysis], str, str]:
    evidence_blob = evidence_rows(envelope)
    claims_blob = [{"claim_id": c.id, "text": c.text} for c in envelope.classification.claims]
    user = (
        "CLAIMS:\n"
        + _json(claims_blob)
        + "\nEVIDENCE:\n"
        + _json(evidence_blob)
    )
    data, provider, model = await llm.chat_json_any(
        attempts=attempts,
        system=GEMINI_SYSTEM,
        user=user,
    )
    rows = data.get("claims") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return [], provider, model
    # Same ids the analyst was shown, so a hallucinated source_id is still
    # dropped rather than silently accepted as evidence.
    valid = {row["source_id"] for row in evidence_blob}
    out: list[GeminiClaimAnalysis] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        slot_rows = []
        for inc in row.get("inconsistencies") or []:
            if not isinstance(inc, dict):
                continue
            slot = inc.get("slot") if inc.get("slot") in {"date", "place", "number", "actor", "other"} else "other"
            slot_rows.append(
                Inconsistency(
                    slot=slot,
                    summary=str(inc.get("summary") or ""),
                    source_ids=[s for s in (inc.get("source_ids") or []) if s in valid],
                )
            )
        out.append(
            GeminiClaimAnalysis(
                claim_id=str(row.get("claim_id") or ""),
                supported_by=[s for s in row.get("supported_by") or [] if s in valid],
                contradicted_by=[s for s in row.get("contradicted_by") or [] if s in valid],
                unrelated=[s for s in row.get("unrelated") or [] if s in valid],
                inconsistencies=slot_rows,
                missing_slots=[str(x) for x in row.get("missing_slots") or []],
            )
        )
    # attach gemini stance onto pair analyses
    stance_map: dict[tuple[str, str], Stance] = {}
    for row in out:
        for sid in row.supported_by:
            stance_map[(row.claim_id, sid)] = "supports"
        for sid in row.contradicted_by:
            stance_map[(row.claim_id, sid)] = "refutes"
        for sid in row.unrelated:
            stance_map.setdefault((row.claim_id, sid), "unrelated")
    for pair in envelope.analysis:
        pair.gemini_stance = stance_map.get((pair.claim_id, pair.source_id))
    return out, provider, model


def evidence_rows(envelope: RunEnvelope) -> list[dict]:
    """The evidence the blinded analyst sees, taken from Layer 3's documents.

    `retrieval.documents` is the authoritative list; `evidence_items` is the
    compat projection of it and carries the same rows in the same order, which
    is why the ids match either way. Reading the documents directly means the
    analyst sees exactly what retrieval kept, including the relevance score and
    the wire credit, rather than a lossy copy.
    """
    retrieval = envelope.retrieval
    if retrieval is not None and retrieval.documents:
        return [
            {
                "source_id": evidence_source_id(index),
                "outlet": hit.publisher_domain or hit.publisher_id,
                "date": hit.published_at,
                "url": hit.url,
                "title": hit.title,
                "snippet": (hit.snippet or "")[:500],
                # Shown so the analyst can see that two rows are one report,
                # not two confirmations. It must not treat it as a quality mark.
                "wire_credit": hit.wire_credit,
            }
            for index, hit in enumerate(retrieval.documents)
        ]
    return [
        {
            "source_id": item.source_id,
            "outlet": item.outlet,
            "date": item.published_at,
            "url": item.url,
            "title": item.title,
            "snippet": item.snippet[:500],
        }
        for item in envelope.evidence_items
    ]


def independent_source_groups(envelope: RunEnvelope) -> dict[str, str]:
    """Map each evidence item onto the independent source it belongs to.

    Layer 3 has already decided which pages come from one newsroom; this just
    joins its grouping back onto the evidence ids Layer 4 reasons about, so a
    claim supported by twenty syndicated copies is scored as one source rather
    than twenty. Returns an empty mapping when Layer 3 produced no retrieval
    payload, in which case the caller falls back to per-masthead counting.
    """
    retrieval = envelope.retrieval
    if retrieval is None or not retrieval.independent_sources:
        return {}

    group_by_url: dict[str, str] = {}
    for source in retrieval.independent_sources:
        for member in source.member_urls:
            group_by_url[member] = source.source_id

    groups: dict[str, str] = {}
    for item in envelope.evidence_items:
        key = canonical_url(item.url) if item.url else ""
        if key in group_by_url:
            groups[item.source_id] = group_by_url[key]
    return groups


def _independent_source_count(envelope: RunEnvelope, evidence) -> int:
    """How many genuinely separate newsrooms are behind the evidence.

    Prefers Layer 3's collapsed count. The publisher-family fallback is the old
    behaviour, kept only for envelopes written before Layer 3 populated
    `retrieval`; it counts mastheads, so it over-reports whenever a story was
    syndicated. It goes away with the compat shim in stage 6.
    """
    retrieval = envelope.retrieval
    if retrieval is not None and retrieval.independent_sources:
        return retrieval.independent_source_count
    return independent_family_count([e.url for e in evidence])


def _json(value) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, indent=2)


def _independent(envelope: RunEnvelope, url: str) -> bool:
    source_family = publisher_family(url)
    origin = envelope.input.publisher_domain
    if not origin:
        return True
    return publisher_family(origin) != source_family


def _temporal(fetch_ts: str | None, published: str | None) -> str:
    if not published:
        return "unknown"
    try:
        pub = datetime.fromisoformat(published.replace("Z", "+00:00"))
        if fetch_ts:
            fetch = datetime.fromisoformat(fetch_ts.replace("Z", "+00:00"))
            return "before" if pub <= fetch else "after"
        return "unknown"
    except Exception:
        return "unknown"
