from __future__ import annotations

import asyncio
from datetime import datetime

from app.config import Settings
from app.engines.llm_router import LLMRouter, pins_temperature
from app.engines.nli import NliEngine
from app.schemas.envelope import (
    GeminiClaimAnalysis,
    Inconsistency,
    PairAnalysis,
    RunEnvelope,
    Stance,
)
from app.scoring.corroboration import (
    build_payload,
    fuse_claim,
    llm_row_participated,
    reason_unscored,
)
from app.retrieval.run import evidence_source_id
from app.scoring.source_independence import publisher_family
from app.scoring.urls import grouping_url
from app.logutil import short_error

# Matches Layers 2 and 5. Recorded on the payload even when gemini-3* cannot
# honour it, so a reader can see that fusion input was sampled.
EVIDENCE_LLM_TEMPERATURE = 0.0

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
    retrieval = envelope.retrieval
    documents = list(retrieval.documents) if retrieval is not None else []
    source_groups, group_join_misses = join_independent_sources(envelope)
    existence_class = retrieval.existence_class if retrieval is not None else "not_found"
    stance_limit = int(getattr(settings, "max_evidence_items", 0) or 0)
    scorable = stance_window(envelope, limit=stance_limit)
    evidence_by_id = {
        evidence_source_id(index): hit.url for index, hit in scorable
    }

    pairs: list[PairAnalysis] = []
    gemini_rows: list[GeminiClaimAnalysis] = []
    analyst_model = "skipped"
    evidence_llm_model: str | None = None
    evidence_llm_temperature: float | None = None
    evidence_llm_temperature_pinned: bool | None = None
    llm_dropped_id_count = 0
    analyst_attempts = [
        ("gemini", settings.evidence_llm_model),
        ("anthropic", settings.documentation_model),
    ]
    run_llm = bool(
        claims and scorable and any(llm.provider_ready(p) for p, _ in analyst_attempts)
    )

    if claims and scorable:
        nli_inputs: list[tuple[str, str, str, str]] = []
        for claim in claims:
            for index, hit in scorable:
                nli_inputs.append(
                    (
                        claim.id,
                        evidence_source_id(index),
                        hit.snippet or hit.title,
                        claim.text,
                    )
                )
        window_note = (
            f"{len(claims)} claims × {len(scorable)} snippets"
            + (
                f" (top {len(scorable)} of {len(documents)} ranked pages)"
                if len(documents) > len(scorable)
                else ""
            )
        )
        await emit(
            layer="evidence",
            parameter="claim×evidence",
            process="DeBERTa MNLI stance",
            tool=settings.nli_model,
            status="running",
            detail=f"{window_note}; one HF call per pair, concurrent with Engine B.",
        )
        if run_llm:
            await emit(
                layer="evidence",
                parameter="claims",
                process="blinded multi-document analysis",
                tool=settings.evidence_llm_model,
                status="running",
                detail="Runs alongside NLI. Analyst does not receive DeBERTa labels or an authenticity target.",
            )

        async def _score_nli():
            return await nli.score_pairs([(p, h) for _, _, p, h in nli_inputs])

        async def _score_llm():
            return await _blinded_analyse(
                envelope, llm, analyst_attempts, evidence_limit=stance_limit
            )

        if run_llm:
            nli_result, llm_result = await asyncio.gather(
                _score_nli(), _score_llm(), return_exceptions=True
            )
        else:
            nli_result = await _score_nli()
            llm_result = None

        if isinstance(nli_result, BaseException):
            raise nli_result
        scored = nli_result
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
        by_id = {evidence_source_id(index): hit for index, hit in scorable}
        for (claim_id, source_id, _, _), (label, score, probs) in zip(nli_inputs, scored):
            hit = by_id[source_id]
            pairs.append(
                PairAnalysis(
                    claim_id=claim_id,
                    source_id=source_id,
                    nli_label=label,
                    nli_score=score,
                    nli_probs=probs,
                    independence=_independent(envelope, hit.url),
                    temporal_relation=_temporal(envelope.input.fetch_timestamp, hit.published_at),
                )
            )
            lexical = nli.engine_name.startswith("lexical")
            await emit(
                layer="evidence",
                parameter=f"claim[{claim_id}]",
                process=f"NLI vs {hit.publisher_domain}",
                tool=nli.engine_name if nli.engine_name.startswith("hf:") else "lexical-nli",
                status="skipped" if lexical else "ok",
                detail=(
                    f"{label} ({score:.2f}) — {hit.title[:80]}"
                    + (
                        " (lexical fallback; contradiction detection unavailable)"
                        if lexical
                        else ""
                    )
                ),
            )

        envelope.analysis = pairs
        if isinstance(llm_result, BaseException):
            analyst_model = "skipped"
            await emit(
                layer="evidence",
                parameter="claims",
                process="blinded multi-document analysis",
                tool=settings.evidence_llm_model,
                status="skipped",
                detail=f"Analyst LLM failed ({short_error(llm_result)}); fusion will use NLI only.",
            )
        elif llm_result:
            gemini_rows, provider, analyst_model, llm_dropped_id_count = llm_result
            evidence_llm_model = analyst_model
            evidence_llm_temperature = EVIDENCE_LLM_TEMPERATURE
            evidence_llm_temperature_pinned = pins_temperature(provider, analyst_model)
            _attach_gemini_stance(envelope, gemini_rows)
            participating_n = sum(1 for row in gemini_rows if llm_row_participated(row))
            drop_note = (
                f"; dropped {llm_dropped_id_count} invented source_id mention(s)"
                if llm_dropped_id_count
                else ""
            )
            if participating_n:
                await emit(
                    layer="evidence",
                    parameter="claims",
                    process="blinded multi-document analysis",
                    tool=analyst_model,
                    status="ok",
                    detail=(
                        f"{provider}/{analyst_model} structured stance for "
                        f"{participating_n} claim(s){drop_note}."
                    ),
                )
            else:
                await emit(
                    layer="evidence",
                    parameter="claims",
                    process="blinded multi-document analysis",
                    tool=analyst_model,
                    status="skipped",
                    detail=(
                        f"{provider}/{analyst_model} returned no usable source_ids"
                        f"{drop_note}; fusion will use NLI only."
                    ),
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
    else:
        await emit(
            layer="evidence",
            parameter="claim×evidence",
            process="DeBERTa MNLI stance",
            tool=settings.nli_model,
            status="empty",
            detail="No claim/evidence pairs to score. Absence is not falsity.",
        )
        await emit(
            layer="evidence",
            parameter="claims",
            process="blinded multi-document analysis",
            tool=settings.evidence_llm_model,
            status="skipped",
            detail="Analyst LLM unavailable or no evidence; fusion will use NLI only.",
        )
        envelope.analysis = pairs

    envelope.engines_used["nli"] = nli.engine_name if pairs else "skipped"

    envelope.gemini_analysis = gemini_rows
    participating_rows = [row for row in gemini_rows if llm_row_participated(row)]
    envelope.engines_used["evidence_llm"] = (
        analyst_model if participating_rows else "skipped"
    )

    gemini_by_claim = {row.claim_id: row for row in participating_rows}
    fused = []
    for claim in claims:
        fused.append(
            fuse_claim(
                claim_id=claim.id,
                pairs=[p for p in pairs if p.claim_id == claim.id],
                gemini=gemini_by_claim.get(claim.id),
                evidence_by_id=evidence_by_id,
                threshold=settings.nli_threshold,
                existence_class=existence_class,
                source_groups=source_groups,
            )
        )

    envelope.corroboration = build_payload(
        claims=fused,
        # Layer 3's count, which has already collapsed wire syndication, shared
        # ownership and reprints. MUST NOT be `len(documents)` or
        # `retrieval.document_count`: those are page counts, and syndication
        # inflates them without adding a single extra newsroom. This is the
        # number the journalist reads as corroboration, so it has to be the
        # number of genuinely separate sources.
        independent_source_count=_independent_source_count(envelope),
        pairs_scored=bool(pairs),
        unscored_reason=reason_unscored(claims=claims, documents=documents, pairs=pairs),
        existence_class=existence_class,
        nli_engine=nli.engine_name if pairs else "",
        nli_can_detect_contradiction=(
            nli.can_detect_contradiction() if pairs else False
        ),
        group_join_misses=group_join_misses,
        llm_dropped_id_count=llm_dropped_id_count,
        evidence_llm_model=evidence_llm_model,
        evidence_llm_temperature=evidence_llm_temperature,
        evidence_llm_temperature_pinned=evidence_llm_temperature_pinned,
    )
    scored = bool(pairs)
    await emit(
        layer="evidence",
        parameter="corroboration",
        process="deterministic fusion",
        tool="fusion",
        status="ok" if scored else "empty",
        detail=(
            f"overall={envelope.corroboration.overall_state}"
            + (
                f"; {envelope.corroboration.unscored_reason}; no pairs scored — not a finding"
                if not scored
                else "; no authenticity score assigned"
            )
            + (
                f"; {group_join_misses} IndependentSource join miss(es) — independent count is an upper bound"
                if group_join_misses
                else ""
            )
            + (
                "; contradiction detection unavailable (lexical NLI)"
                if scored and not envelope.corroboration.nli_can_detect_contradiction
                else ""
            )
            + "."
        ),
    )


async def _blinded_analyse(
    envelope: RunEnvelope,
    llm: LLMRouter,
    attempts: list[tuple[str, str]],
    *,
    evidence_limit: int = 0,
) -> tuple[list[GeminiClaimAnalysis], str, str, int]:
    payload = blinded_analyst_payload(envelope, evidence_limit=evidence_limit)
    evidence_blob = payload["evidence"]
    user = (
        "CLAIMS:\n"
        + _json(payload["claims"])
        + "\nEVIDENCE:\n"
        + _json(evidence_blob)
    )
    data, provider, model = await llm.chat_json_any(
        attempts=attempts,
        system=GEMINI_SYSTEM,
        user=user,
        temperature=EVIDENCE_LLM_TEMPERATURE,
    )
    rows = data.get("claims") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return [], provider, model, 0
    # Same ids the analyst was shown, so a hallucinated source_id is still
    # dropped rather than silently accepted as evidence.
    valid = {row["source_id"] for row in evidence_blob}
    out: list[GeminiClaimAnalysis] = []
    dropped_mentions = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        supported, drop_s = _keep_valid_ids(row.get("supported_by"), valid)
        contradicted, drop_c = _keep_valid_ids(row.get("contradicted_by"), valid)
        unrelated, drop_u = _keep_valid_ids(row.get("unrelated"), valid)
        slot_rows = []
        drop_i: list[str] = []
        for inc in row.get("inconsistencies") or []:
            if not isinstance(inc, dict):
                continue
            slot = inc.get("slot") if inc.get("slot") in {"date", "place", "number", "actor", "other"} else "other"
            kept_ids, dropped_ids = _keep_valid_ids(inc.get("source_ids"), valid)
            drop_i.extend(dropped_ids)
            slot_rows.append(
                Inconsistency(
                    slot=slot,
                    summary=str(inc.get("summary") or ""),
                    source_ids=kept_ids,
                )
            )
        dropped = _unique(drop_s + drop_c + drop_u + drop_i)
        dropped_mentions += len(drop_s) + len(drop_c) + len(drop_u) + len(drop_i)
        out.append(
            GeminiClaimAnalysis(
                claim_id=str(row.get("claim_id") or ""),
                supported_by=supported,
                contradicted_by=contradicted,
                unrelated=unrelated,
                inconsistencies=slot_rows,
                missing_slots=[str(x) for x in row.get("missing_slots") or []],
                dropped_source_ids=dropped,
            )
        )
    return out, provider, model, dropped_mentions


def _attach_gemini_stance(
    envelope: RunEnvelope, rows: list[GeminiClaimAnalysis]
) -> None:
    stance_map: dict[tuple[str, str], Stance] = {}
    for row in rows:
        if not llm_row_participated(row):
            continue
        for sid in row.supported_by:
            stance_map[(row.claim_id, sid)] = "supports"
        for sid in row.contradicted_by:
            stance_map[(row.claim_id, sid)] = "refutes"
        for sid in row.unrelated:
            stance_map.setdefault((row.claim_id, sid), "unrelated")
    for pair in envelope.analysis:
        pair.gemini_stance = stance_map.get((pair.claim_id, pair.source_id))


def stance_window(envelope: RunEnvelope, *, limit: int) -> list[tuple[int, object]]:
    """Ranked snippets both engines score, capped at max_evidence_items.

    Layer 3 keeps every page so syndication can be counted honestly. Layer 4
    must not MNLI-score that full list: each pair is an HTTP call. The window
    is the already-ranked documents that have text, truncated to ``limit``.
    """
    retrieval = envelope.retrieval
    if retrieval is None:
        return []
    ranked = [
        (index, hit)
        for index, hit in enumerate(retrieval.documents)
        if (hit.snippet or hit.title or "").strip()
    ]
    if limit > 0:
        return ranked[:limit]
    return ranked


def blinded_analyst_payload(
    envelope: RunEnvelope, *, evidence_limit: int = 0
) -> dict[str, list]:
    """The exact JSON Engine B is sent. This is the blinding boundary.

    Engine B sees every Layer 2 claim (checkworthy or not) and the evidence
    rows below. It does not see NLI labels, existence class, or Layer 3's
    syndication judgement. Fusion, not the analyst, collapses wire copies.
    """
    return {
        "claims": [
            {"claim_id": c.id, "text": c.text}
            for c in envelope.classification.claims
        ],
        "evidence": evidence_rows(envelope, limit=evidence_limit),
    }


def evidence_rows(envelope: RunEnvelope, *, limit: int = 0) -> list[dict]:
    """The evidence the blinded analyst sees, taken from Layer 3's documents.

    Ids are `s1`, `s2`, … in document order — the same scheme NLI uses — so a
    hallucinated source_id that is not in this list is dropped. Only the
    snippet the journalist would also see is included: outlet, date, url,
    title, text. Layer 3 judgements (wire credit, merge reason, existence,
    relevance) stay off this list so Engine B cannot be steered by them.
    """
    return [
        {
            "source_id": evidence_source_id(index),
            "outlet": hit.publisher_domain or hit.publisher_id,
            "date": hit.published_at,
            "url": hit.url,
            "title": hit.title,
            "snippet": (hit.snippet or "")[:500],
        }
        for index, hit in stance_window(envelope, limit=limit)
    ]


def join_independent_sources(envelope: RunEnvelope) -> tuple[dict[str, str], int]:
    """Map each document id onto the independent source it belongs to.

    Layer 3 has already decided which pages come from one newsroom; this just
    joins its grouping back onto the ids Layer 4 reasons about, so a claim
    supported by twenty syndicated copies is scored as one source rather than
    twenty. Both sides of the join use ``grouping_url``. A miss falls through
    to counting the document id as its own source, which inflates the
    independent count — ``group_join_misses`` records how often that happened.
    """
    retrieval = envelope.retrieval
    if retrieval is None:
        return {}, 0
    if not retrieval.independent_sources:
        return {}, len(retrieval.documents)

    group_by_url: dict[str, str] = {}
    for source in retrieval.independent_sources:
        for member in source.member_urls:
            group_by_url[member] = source.source_id

    groups: dict[str, str] = {}
    misses = 0
    for index, hit in enumerate(retrieval.documents):
        key = grouping_url(hit)
        if key in group_by_url:
            groups[evidence_source_id(index)] = group_by_url[key]
        else:
            misses += 1
    return groups, misses


def independent_source_groups(envelope: RunEnvelope) -> dict[str, str]:
    groups, _misses = join_independent_sources(envelope)
    return groups


def _keep_valid_ids(values, valid: set[str]) -> tuple[list[str], list[str]]:
    kept: list[str] = []
    dropped: list[str] = []
    for item in values or []:
        sid = str(item)
        if sid in valid:
            kept.append(sid)
        elif sid:
            dropped.append(sid)
    return kept, dropped


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in values:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _independent_source_count(envelope: RunEnvelope) -> int:
    """How many genuinely separate newsrooms are behind the evidence.

    This is Layer 3's collapsed count. It is not `len(documents)` and not
    `document_count`: those are page counts, inflated by syndication, and using
    either as corroboration is the defect this rewrite removes.
    """
    retrieval = envelope.retrieval
    if retrieval is None:
        return 0
    return retrieval.independent_source_count


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
