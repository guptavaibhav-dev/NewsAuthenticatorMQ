# COMP4092 Thesis B — Meeting logs (Weeks 6–8)

**Student:** Vaibhav Gupta
**Unit:** COMP4092 Software Engineering Research Thesis B
**Project:** A Framework for Authenticating News Content (NewsAuth prototype)
**Session:** Session 2, 2026 (classes from 27 July)

Continues from `meeting-logs/weeks-03-to-05.md`. Teaching-week dates:

| Week | Dates |
|------|--------|
| 6 | 31 August – 6 September 2026 |
| 7 | 7–13 September 2026 |
| 8 | 14–20 September 2026 (entries below run to 16 September) |

---

## Week 6 (31 August – 6 September 2026)

**Hours:** ~8

### Planned this week

Carried forward from Week 5:

- Re-run the ABC Nepal case (and 1–2 contrast URLs) after failover; confirm Pre-process / Evidence / Record are `ok` or honestly `skipped`, not silently dummy-scored.
- Restore or replace the OpenAI preprocess path; confirm HF NLI returns non-neutral distributions on real pairs.
- Freeze 3–5 thesis demo cases (true coverage, single-source, contested, rumour).
- Tighten the health panel so “ready” reflects last successful engine call, not only key presence.
- Start the write-up: limitations of aggregators, snippet NLI, and why disagreement is a feature.

### Work completed

Did **not** freeze cases or re-run ABC this week. The Week 5 pipeline still ran all layers in one shot once `/api/runs` was posted, which made the “human-led” claim a post-hoc save-decision rather than a stop at each layer. That became the increment.

**4 September — step-through inspector (commit `fcab316` *unfinished end to end changes*)**

- Rewrote the orchestrator so a run **stops after each layer** (`phase: awaiting_decision`). The journalist chooses Proceed, Re-run, or (on layer 6) records an editorial label. Layer 6 cannot be generated or re-run by the system (`POST /api/runs/{id}/step`, `POST /api/runs/{id}/decision`).
- Layer snapshots on the run store: Re-run restores the envelope to the start of the current layer instead of accumulating a second copy of the trace.
- Added `POST /api/runs/{id}/ask`: a read-only assistant that may explain the current layer’s output and must not mutate the run or issue a true/false verdict (`backend/app/pipeline/ask.py`).
- Replaced the single-shot result panel with `InspectorChat`: one card per completed layer, Proceed / Generate response / Ask on the current layer, Confirm on the editorial layer.
- Split layer UI into `layerOutputs.tsx` (what this layer produced), `layerProcess.tsx` (process-per-parameter timeline), `processKit.tsx`.
- Persist runs under `backend/.runs/{run_id}.json` (gitignored). If the API restarts mid-layer, the envelope is marked error and the journalist is told to Generate response again.
- Vite proxy timeouts set to 0 so long Layer 3/4 calls are not cut by the dev server.

### Evidence

- Git commit `fcab316` (4 Sep 2026): *unfinished end to end changes* — 22 files, +2953 / −445. Key files: `backend/app/main.py`, `backend/app/pipeline/orchestrator.py`, `backend/app/pipeline/ask.py`, `backend/app/pipeline/store.py`, `src/App.tsx`, `src/components/InspectorChat.tsx`.
- Dashboard now requires an explicit Proceed between layers; editorial Confirm is the only way Layer 7 starts.
- Week 5 next-step items (ABC re-run, frozen case set, health-panel tightening, write-up) were **not** closed this week.

### Decisions and rationale

- **Stop after every layer, not only at the end.** Thesis A’s human-led principle is empty if layers 1–5 race to a recommendation and the journalist only rubber-stamps Layer 6. A stop lets them reject a bad claim split or a bad search before NLI runs.
- **Re-run is restore-and-repeat, not append.** Without snapshots, a second Layer 3 pass would look like twice as much coverage.
- **Ask is read-only.** An inspector that can rewrite claims or scores would become a hidden eighth engine. The system prompt forbids authenticity verdicts and speculation about layers that have not run.
- **Deferred the Week 5 evaluation freeze.** A one-shot pipeline was the wrong surface on which to freeze “what the journalist is expected to see.” The inspector had to exist first.

### Problems and blockers

- Commit message is honest: the step-through is “unfinished end to end.” Layer cards still followed the Week 5 envelope (old sequential verification tools, publisher-family counts). The inspector made that structure visible; it did not yet fix it.
- ABC re-run, OpenAI billing, HF NLI confirmation, and the 3–5 case freeze remain open.
- Runs live in gitignored `.runs/`, so a demo artefact disappears from git history unless copied out.
- Long Gemini/Claude calls still sit under the 90s timeout from Week 5; the proxy no longer aborts them, but the model still can.

### Reflection

Week 5 proved the pipeline could complete. Week 6 proved it could *pause*. That is the more important research move for a human-led framework: the journalist is in the loop as a controller of each stage, not as a consumer of a finished authenticity report. The cost is that evaluation cases still are not frozen, and the layers the journalist is now inspecting still over-count syndication and still treat “verification” as a bag of vendor APIs. Those are Week 7–8 problems; they were not going to be visible while the UI fired all seven layers at once.

### Next steps

- Rebuild Layer 1 so a failed or paywalled fetch is a named coverage gap (`fetch_reason`), not a vague error.
- Rebuild Layer 2 so claims are grounded in the article and extracted twice, because a single LLM pass is not a cross-check.
- Specify Layer 3 as retrieval + independence (queries frozen before HTTP; newsrooms not pages) before wiring new adapters.
- Keep diagrams generated from code, not hand-drawn, so the write-up cannot drift from the prototype.
- The Week 5 case-freeze and ABC re-run stay on the list.

### Questions for supervisor

- Is a journalist-gated step-through the right operationalisation of “human-led”, or do you still want a one-click full run for the demo?
- Should Ask (the inspector LLM) stay in the evaluated prototype, or is it a convenience that complicates the “no extra judgement engine” claim?
- Given Week 5’s Nepal run already showed corroborating outlets, is it acceptable to delay the frozen case set until Layers 1–3 are rebuilt, so the cases are run on the architecture we will actually write up?

---

## Week 7 (7–13 September 2026)

**Hours:** ~12

### Planned this week

- Translate Layers 1–3 from the Week 5 implementation into something that can be defended in the report: named fetch failures, grounded claims, a retrieval plan that is frozen before any HTTP call.
- Produce architecture diagrams that match the code, not a parallel sketch.
- Leave media/C2PA unwired on purpose, with a test that Layer 1 does not call it.
- Still outstanding: freeze 3–5 cases; ABC re-run; health-panel “last success” probe.

### Work completed

**12 September — generated layer diagrams (commit `917e59e` *documentation*)**

- Added Python generators under `docs/excalidraw/_generate_*_layer.py` and wrote `.excalidraw` artefacts for Layers 1–4, 6 and 7 (Layer 5 followed on 13 September).
- Diagrams are generated, not hand-edited. Each footer lists the source-of-truth modules.

**13 September — Layers 1–2 rebuilt; Layer 3 specified but not wired (commit `570027c` *1/2 changes till layer 3*)**

Layer 1 — Input:

- `fetch_reason` taxonomy (`ok`, `skipped_no_url`, `empty_paywall` / `empty_js_required` / `empty_not_article`, `error_dns` / `error_timeout` / `error_tls` / `error_blocked` / `error_not_found` / `error_server` / `error_unsupported_type` / `error_too_large` / `error_other`). A non-ok reason is a coverage gap, never falsity.
- Canonical URL (redirect unwrap, same-domain canonical/og:url, AMP unwrap, tracking-param strip) and `publisher_id` (platform hosts vs registrable domain).
- Paste vs fetched body recorded as tiling `segments`, so later layers do not guess where characters came from.
- Bot User-Agent `NewsAuthBot/1.0 (+CONTACT_URL)`.
- `media.py` rewritten as documentation-only. `inspect_media` is absent; tests assert Layer 1 does not call it. README Future work records C2PA / reverse-image as not wired.

Layer 2 — Pre-processing:

- Two independent extraction passes (`CLAIM_PASSES=2`), different system prompts, claims matched by span overlap not by wording (`claim_agreement.py`). `agreement` is extractor overlap, never a truth score. `passes_independent` is true only when the two passes used different models.
- Every claim must quote the article; ungrounded quotes are kept and flagged, never dropped (`grounding.py`).
- NER still runs in parallel; disagreements are forwarded.

Layer 3 — specified, not yet the live path:

- Deterministic planner (`planner.py`, template `l3-v1`): select top-k *searchable* claims, build existence / claim / fact-check / entity queries. LLM rewrite off by default and only accepted whole.
- `RetrievalPayload` schema written (`schemas/retrieval.py`). Old sequential `layers/verification.py` still ran in the orchestrator (“1/2 changes”).
- Cursor rule `keep-diagrams-in-sync.mdc`: regenerate the matching diagram in the same change as a layer’s code.

Tests added (planner, schema, fetch_reason, ingest segments, bot identity, publisher_id, canonical URL, claim grounding, claim agreement, media unwired). Layer 5 diagram generated.

### Evidence

- Commits:
  - `917e59e` (12 Sep) — diagram generators + `.excalidraw` files.
  - `570027c` (13 Sep) — ingest/preprocess/planner/schema/tests; 44 files, +10916 / −893.
- Tests from this week’s new modules (later counted in the full suite; this commit introduced them). Key files: `backend/app/tools/ingest.py`, `backend/app/layers/preprocess.py`, `backend/app/layers/claim_agreement.py`, `backend/app/layers/grounding.py`, `backend/app/retrieval/planner.py`, `backend/tests/test_retrieval_planner.py`.
- Explicit non-goal: `backend/tests/test_media_unwired.py` — C2PA is future work, not a silent stub.

### Decisions and rationale

- **Failed fetch ≠ fake.** Paywall, JS-only page, 403, timeout are coverage gaps. Treating them as negative evidence would make “we could not read it” look like “it is false.”
- **Ground claims or keep them flagged.** Dropping an ungrounded quote would hide extractor hallucination; the journalist needs to see it.
- **Agreement is span overlap, not paraphrase similarity.** Two wordings of the same sentence should match because they point at the same characters; two different sentences should not match because they read alike.
- **Planner is deterministic and frozen later (Week 8) before HTTP.** A search that cannot be reproduced cannot be audited. Scoring is “how searchable,” never “how true.” An unselected claim is unsearched, not unsupported.
- **Media stays out of Layer 1.** A missing Content Credential must not become a falsity signal, and a stub trace entry would be noise in every text-only run.
- **Diagrams generated from code.** Hand-edited Excalidraw would diverge from the envelope the week we needed figures for the report.

### Problems and blockers

- Layer 3 is a schema and a planner sitting beside the old `verification.py` path. The dashboard still ran the Week 5 vendor-API sequence. Commit message: “1/2 changes till layer 3.”
- Dual-pass independence requires two *different* models. If only Anthropic is up, both passes are Claude and `passes_independent` is false — a cross-check in shape only. Observed later (Week 8 live run).
- Case freeze, ABC re-run, and health-panel tightening still not done. No stakeholder contact.
- Arbitrary constants already visible in the planner (`retrieval_top_k_claims` default 5) — labelled for later experimental determination, not validated this week.

### Reflection

The research content this week is the distinction between **signal collection** and **judgement**, written into Layer 1 and 2 instead of only into comments. Fetch reasons, grounded claims, and “unsearched ≠ unsupported” are the same thesis rule as Week 5’s “empty NewsAPI ≠ fake,” applied one layer earlier. The diagrams make that rule visible for the report. The incomplete half is still the one that will show up in evaluation: until Layer 3 actually retrieves and counts newsrooms, the inspector is stepping through a layer whose name (“Verification Tool”) promises more than the old implementation could defend.

### Next steps

- Wire the new retrieval adapters and independence collapse; keep the old envelope fields as a compat shim so the frontend does not go blank.
- Delete the sequential verification tools once the new path is the only path.
- Rebuild Layer 4 fusion so corroboration counts independent sources, not URLs, and so `not_found` (looked, nothing) stays distinct from `out_of_range` (never looked).
- Measure old vs new independence counts on syndication fixtures before the old counter is deleted.
- Then freeze cases — not before, or the expected traces will describe an architecture we have already replaced.

### Questions for supervisor

- Is renaming Layer 3’s *display* title to “Retrieval and Independence” (keeping the id `verification` for the trace) an acceptable refinement of Thesis A, or must the report keep “Verification Tool Layer” as the heading?
- Are NewsAPI + Guardian + GNews/Newsdata + GDELT + Google Fact Check + Wikipedia an acceptable instantiation of that layer, given Thesis A does not name vendors?
- v1 is text/URL only. Is dropping reused-image / AI-media cases from this session’s evaluation acceptable if C2PA is written up as future work with the “missing credential ≠ fake” rule already on `media.py`?

---

## Week 8 (14–16 September 2026; week runs to 20 September)

**Hours:** ~12 (through 16 September)

### Planned this week

- Finish the second half of Layer 3: capability-gated adapters, existence ladder, independence collapse, coverage report.
- Point Layers 4, 5 and 7 at newsrooms rather than pages; stop treating syndication as corroboration.
- Record the old-vs-new counter on fixtures while both paths still exist.
- Live-run a real article on the new path.
- Still outstanding from Week 5: ABC re-run, 3–5 frozen cases, health-panel tightening, aggregator/snippet-NLI write-up.

### Work completed

**15 September — Layer 3 goes live (commit `27d8139` *Wire Layer 3 retrieval while keeping the old envelope fields as a compat shim.*)**

- Adapters behind one capability gate: Guardian, NewsAPI, GNews, Newsdata, GDELT (article search); Google Fact Check and Wikipedia wired separately. Missing key → `skipped_no_key`. Article older than a declared archive → `skipped_out_of_range`. Those statuses are never mapped to `not_found`.
- Queries written onto the envelope **before** any HTTP call. Re-run replays that plan.
- Existence ladder: quoted headline, then loose, then keywords; stop at the first rung that hits. Empty ladder (`not_planned`) ≠ exhausted search.
- Dedupe pages (same URL / near-identical text from one publisher), then collapse newsrooms: `same_wire`, then `same_owner`, then `reprint`. Two numbers on the payload: `document_count` (pages) and `independent_source_count` (newsrooms). Only the second bears on corroboration.
- Ownership map `publisher_ownership.json`: 154 domains, 68 groups. A missing domain is counted independent (overstatement is visible; guessing a parent would silently erase reporting).
- Display title “Retrieval and Independence”; trace id stays `"verification"` so the frontend filter keeps working.
- Ranking records its engine (`embedding` vs char-ngram). Floor 0.22 and near-duplicate 0.88 are documented as char-trigram-tuned and **not** transferred silently to embeddings.

**15 September — live URL on the new Layer 3** (envelope `backend/.runs/42a20481-2c26-463f-bbe8-47aef31f4ccd.json`, gitignored; created `2026-09-15T09:49:44Z`)

- URL: Nine.com.au, “Major Australian fashion brands Cue and Veronika Maine enter administration” (slug `20260915`). URL-only ingest, HTTP 200, 2614 characters.
- Layer 2: 9 claims, agreement rate 0.7778, but `passes_independent=false` (both passes `claude-sonnet-4-6`).
- Layer 3: `existence_class=title_match` (loose); 36 documents / 11 independent sources; Guardian 48 hits ok, NewsAPI 10 ok, GNews empty, Newsdata HTTP 422 (`from_date` unsupported on `/1/news`), GDELT phrase-length error, Fact Check empty, Wikipedia 25 hits.
- Layer 4 (still the pre-rewrite path on this run): 9×36 = 324 pairs; Hugging Face HTTP **402** depleted credits → `lexical-nli-fallback`; `nli_can_detect_contradiction=false`; overall `no_corroboration_found` despite at least one on-topic Guardian title in the hit list and many off-topic pages (ranking/snippet problem).
- Layer 5: risk `high`, recommended `unverifiable` (Claude). Layers 6–7 not run (`phase=awaiting_decision` at layer 5). Not a finished case.

**16 September — Layer 4 rewrite; old verification path removed (commit `d1d7a78` *changes*)**

- Deleted `layers/verification.py` and `tools/{newsapi,guardian,gnews,factcheck,wikipedia}.py`. Layer 3 is only `retrieval/`.
- Engine A (DeBERTa MNLI, then BART, then lexical) and Engine B (blinded Gemini, then Claude) score a capped snippet window (`max_evidence_items`, default 12), not every retrieved page. Engine B is forbidden NLI labels, existence class, relevance, merge reason, and wire credit (`test_evidence_blinding.py`).
- Fusion counts support/contradiction by Layer 3 independent-source groups. Empty paths are `not_assessed`, never `no_corroboration_found`. `not_found` and `out_of_range` stay distinct.
- Lexical NLI cannot see antonym contradiction (`posted a profit` vs `posted a loss`); that is a strict xfail, not a pass (`test_nli_engine.py`).
- Layers 5 and 7 consume the new payload (independence note states pages and sources together; documentation cites one URL per newsroom, not per syndicated page).
- Recorded old vs new counters while both still existed: `backend/app/retrieval/EVALUATION.md`. Twenty Reuters copies: old `independent_family_count` **19**, new `independent_source_count` **1** (`same_wire`). That comparison cannot be reproduced now the old path is gone.
- Full backend suite on 16 September: **321 passed, 1 xfailed**.

### Evidence

- Commits:
  - `27d8139` (15 Sep) — adapters, independence, ladder, ranking, ownership map, orchestrator switch; 36 files, +7236 / −853.
  - `d1d7a78` (16 Sep) — Layer 4 fusion/blinding, Layer 5/7 consumers, `EVALUATION.md`, `retrieval/README.md`, delete old verification tools; 45 files, +2795 / −2046.
- Fixture table: `backend/app/retrieval/EVALUATION.md` (twenty_reuters_copies 20→1; five_reuters_plus_bbc_original 6 pages / old 5 / new 2).
- Live envelope (local, not in git): Nine.com.au run above. Journalist decision not recorded.
- Tests: `test_independence.py` (`test_twenty_papers_one_reuters_story_is_one_source`), `test_retrieval_integration.py`, `test_evidence_fusion.py`, `test_evidence_blinding.py`, `test_nli_engine.py`.
- Design notes: `backend/app/retrieval/README.md` (limitations: ownership map incomplete, wire bylines often absent, language/age gates never fire because `article_language` and `published_at` are always `None` today).

### Decisions and rationale

- **Volume is not corroboration.** Twenty mastheads reprinting one Reuters story are one newsroom. Counting pages (or even masthead families without the wire credit) would have told the journalist that nineteen sources confirmed a story one agency wrote. That is the headline result of `EVALUATION.md`, and the reason Layer 4 now joins Layer 3 groups instead of `publisher_family`.
- **Capability skips are not “not found.”** `not_found` means we looked and saw nothing. `out_of_range` / `skipped_no_key` mean we never looked. Flattening them would turn our own archive limit into apparent absence of the story.
- **Over-count missing owners, do not guess.** An unmapped domain stays independent. The error is in the direction a journalist can check by hand.
- **Blind Engine B.** If Gemini sees DeBERTa labels or “this is a wire copy,” disagreement is no longer an independent signal.
- **Lexical NLI is a last resort and must say so.** `nli_can_detect_contradiction=false` is on the payload so a zero contradiction count is not a finding. The xfail test is there so nobody “fixes” the heuristic by making antonyms look solved.
- **The Nine.com.au run is a smoke test, not a thesis case.** It stopped at Layer 5, used lexical NLI, and retrieved off-topic pages. It is evidence about the pipeline’s failure modes, not a completed evaluation of the article.

### Problems and blockers

- Hugging Face Inference credits depleted (HTTP 402) on the 15 September run; DeBERTa did not score that article. Same class of problem as Week 5’s retired HF URL, different endpoint.
- Newsdata `from_date` 422 on `/1/news` — still present in the adapter after 16 September; not yet fixed.
- GDELT rejects long quoted headlines.
- Embedding ranking + 0.22 floor (trigram-tuned) admits off-topic hits; the Nine.com.au independent-source list included Pixel reviews, Bitcoin, Marvel rankings alongside one on-topic Guardian title.
- Age and language gates never fire in live runs (`published_at` and `article_language` are always `None` on `article_context`).
- Dual-pass claims used the same Claude model twice on that run, so the 77.78% agreement rate is not a cross-check.
- OpenAI preprocess path still not confirmed restored (Week 5 blocker).
- **Still no frozen 3–5 cases, no ABC re-run artefact, no stakeholder feedback, no scores against the seven Thesis A criteria.**
- Health panel still keys-present ≠ last-success (Week 5 next step, not done).
- README architecture blurb still says “Verification Tool Layer” and Gemini 2.5 Pro; code is Retrieval and Independence + `gemini-3.6-flash`.

### Reflection

Weeks 6–8 turned the Week 5 “it runs” prototype into the architecture the thesis can actually argue: the journalist gates each layer; a failed fetch is a gap; claims are grounded; searches are frozen; corroboration is counted in newsrooms; disagreement and empty tools stay visible; nobody auto-commits a verdict. The syndication fixture (20 pages → 1 source) is the first result that is about the *framework*, not about keeping the demo alive.

The live Nine.com.au run is the second Nepal-style lesson: a green Layer 3 hit count is not corroboration if ranking is off-topic and NLI has fallen back to lexical overlap. `no_corroboration_found` on a widely reported administration story is a pipeline exhibit, and it would have been a dishonest case-study verdict. That is why cases are still not frozen. The remaining Thesis B risk is no longer “will there be a prototype”; it is “will there be three finished, honest cases on this architecture before 8 November.”

### Next steps

- Restore HF NLI credits (or another MNLI host); re-run a widely reported article and confirm Engine A is `hf:…` with non-neutral distributions.
- Fix Newsdata `from_date` (do not send an unsupported parameter) and tighten GDELT query length.
- Do not apply the 0.22 relevance floor to embedding scores, or retune it; record whichever choice.
- Capture `published_at` and detect article language so the capability gates can actually fire.
- Freeze 3 text cases on the *new* path (true coverage, contested / conflicting, rumour or single-source), run Layers 1–7 including a human Layer 6 label, and copy envelopes out of `.runs/` into a keepable `cases/` folder.
- Re-run the Week 5 ABC Nepal URL on the new Layer 3 if the URL is still available.
- Align README with `config.py`. Export the Excalidraw diagrams to PNG/PDF for the report.
- Decide with the supervisor: stakeholder think-alouds this session, or an explicit scope drop.

### Questions for supervisor

- For evaluation, is a qualitative walkthrough of 3 frozen URLs on this architecture enough, or do you still want inter-rater agreement between journalists using the dashboard?
- Should the Nine.com.au run be kept as a *limitations* exhibit (lexical NLI + off-topic retrieval → `no_corroboration_found`) rather than as a case?
- Publication-risk and `recommended_decision` are still shown to the journalist. Does that nudge the human, and should Layer 6 show only the matrix + unknowns?
- Are you comfortable treating documented failover and the 20→1 syndication result as part of the contribution (robust, non-misleading decision-support) rather than as implementation defects?
- Confirm: COMP4092 on the dashboard/README vs COMP4093 on the Layer 4 diagram — which unit code should the report use?
