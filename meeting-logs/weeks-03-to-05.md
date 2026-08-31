# COMP4092 Thesis B — Meeting logs (Weeks 3–5)

**Student:** Vaibhav Gupta
**Unit:** COMP4092 Software Engineering Research Thesis B
**Project:** A Framework for Authenticating News Content (NewsAuth prototype)
**Session:** Session 2, 2026 (classes from 27 July)

Teaching-week dates used below:

| Week | Dates |
|------|--------|
| 3 | 10–16 August 2026 |
| 4 | 17–23 August 2026 |
| 5 | 24–30 August 2026 |

---

## Week 3 (10–16 August 2026)

**Hours:** ~8

### Planned this week

- Start Thesis B implementation of the journalist-facing dashboard.
- Produce a runnable UI stub so later model/pipeline work has a front end to attach to.
- Keep visual identity aligned with a serious editorial tool (not a consumer “fact-check” product).

### Work completed

- Scaffolded the **NewsAuth** dashboard as a Vite + React + TypeScript app.
- Built the first authenticate screen: paste news text → run → result panel.
- Implemented `authenticateNewsStub` as a placeholder model call (fake latency and verdict) so the UI could be tested without a backend.
- Applied a black-and-white theme with **Lora** as the typeface.
- Confirmed a production build and ran the stub locally at `http://localhost:5173/`.
- Left the seven-layer Thesis A architecture out of this increment on purpose (UI first, framework later).

### Evidence

- Git commit `f3ca293` (11 Aug 2026): *initial commit* — dashboard stub, Lora/B&W theme, stub authenticator.
- Runnable app: `npm run dev`.
- Key files: `src/App.tsx`, `src/lib/authenticateStub.ts`, `src/index.css`.

### Decisions and rationale

- **UI before the pipeline.** Thesis A already specified the 7-layer workflow. Thesis B needed a concrete surface journalists would use; a stub lets that surface exist before APIs and models are wired.
- **No true/false product chrome yet.** The stub still returned a placeholder “verdict” for layout testing, but it was labelled as a stub so it would not be mistaken for the framework.
- **Black-and-white + Lora.** Reads as an editorial workstation rather than a colourful consumer tool, which matches the journalist-centred thesis framing.

### Problems and blockers

- Initial Vite scaffold did not produce a React template as expected; had to install React and pin Vite 5 for a stable local build.
- No backend, no live APIs, and no layer trace yet — expected at this stage.

### Reflection

The stub is enough to demonstrate “there is a dashboard,” but it is not yet the thesis. The stub’s verdict language is actually in tension with the framework (the system must not auto-judge authenticity). That tension is useful: it shows why the next increment has to replace the stub with evidence, uncertainty, and a human decision control.

### Next steps

- Translate Chapter 4 into an implementable architecture (heterogeneous engines, real news APIs, typed run envelope).
- Choose backend stack and provider mix.
- Support URL intake as well as pasted text.

### Questions for supervisor

- Is a UI-first increment acceptable as the Week 3 artefact, or should the first demo already show layer names from Chapter 4?
- Preferred evaluation cases from Thesis A Table 4.1 (misleading claim, conflicting reports, rumour) — should those drive the first live demo?

---

## Week 4 (17–23 August 2026)

**Hours:** ~8

### Planned this week

- Turn Thesis A Chapter 4 into a technical specification that can be built in Thesis B.
- Decide how “verification” is operationalised with *public* news APIs (the thesis names the layer, not vendor APIs).
- Keep judgement non-unilateral: different engines per layer, no single model issuing a truth verdict.

### Work completed

- Re-read Chapter 4 and restated the seven layers in implementation order: Input → Pre-processing and Classification → Verification Tool → Evidence Analysis → Uncertainty and Risk → Human Editorial Decision → Output and Documentation.
- Clarified the two verification questions the tools must answer:
  1. **Existence** — does this same article (or a near-duplicate) appear on a public portal?
  2. **Type / event coverage** — do independent outlets report this *kind* of event?
- Specified a third supporting check: prior **ClaimReview** via Google Fact Check Tools (a prior editorial rating, not our verdict).
- Selected the stack: **React dashboard kept**; **Python FastAPI** orchestrator (stronger for NLP, retrieval, and academic pipelines); secrets stay on the server.
- Drafted the heterogeneous engine map so no layer rubber-stamps another:
  - Preprocess: GPT-4.1 + independent NER
  - Verification query planner: Claude (queries only, no truth score)
  - Evidence: DeBERTa MNLI (non-generative) + blinded Gemini + deterministic fusion
  - Uncertainty: conservative OpenAI model on *structured scores only*
  - Documentation: Claude writes the citation-backed record
  - Editorial decision: dashboard only
- Identified real APIs: NewsAPI, Guardian Open Platform, GNews/NewsData, Google Fact Check Tools, Wikipedia/Wikidata.
- Defined the **run envelope** (typed contract between layers) and the rule that missing/empty tools are **uncertainty**, not “fake”.
- Noted free-tier limits (NewsAPI ~100 calls/day) and that aggregator coverage is incomplete — these belong in the write-up and UI caveats.

### Evidence

- Architecture notes feeding the Week 5 implementation plan (Verification and Evidence Analysis Architecture).
- Thesis A Chapter 4 as the source of layer names and human-led design principles.
- No large code commit this week: this was the design/specification week before the 24 August implementation burst.

### Decisions and rationale

- **Python FastAPI, not Node.** The dashboard is TypeScript; the pipeline is retrieval + NLI + scoring. FastAPI fits the academic prototype and Pydantic envelopes.
- **Pinned models per layer.** Sharing one LLM across judgement layers would make the “non-unilateral” claim hollow.
- **No authenticity score.** Fusion produces corroboration *states* (`event_corroborated`, `single_source`, `contested_reporting`, `no_corroboration_found`, …), not a fake-news probability.
- **Independence counted by publisher family**, not by URL count (BBC.com and BBC.co.uk are one family).
- **Media/C2PA deferred.** Architecture leaves a `MediaTools` hook; v1 is text + URL.

### Problems and blockers

- Thesis A does not name vendor APIs; mapping Chapter 4 onto NewsAPI/Guardian/Fact Check is a Thesis B design choice that needs supervisor agreement.
- API keys and quotas not yet proven end-to-end (work for Week 5).
- Free-tier recency windows mean “no hit” cannot be treated as fabrication.

### Reflection

The important design move this week was separating **signal collection** from **judgement**. If the query-planner LLM is allowed to score truth, or if empty NewsAPI results become a negative score, the prototype stops being the thesis. Writing that down before coding reduced the risk of building an automated fact-checker by accident.

### Next steps

- Implement the FastAPI skeleton, envelope, SSE trace, and Vite `/api` proxy.
- Implement ingest + all seven layers behind the existing dashboard.
- Replace the stub verdict with the process timeline, claim–evidence matrix, and human editorial control.

### Questions for supervisor

- Are NewsAPI + Guardian + Fact Check Tools an acceptable *instantiation* of the Verification Tool Layer, given they are not named in Thesis A?
- Is showing engine disagreement (DeBERTa vs Gemini) as a first-class UI state acceptable, or do you want a single fused recommendation more prominently?
- For evaluation, is a small set of live URLs enough, or do you want a frozen fixture set so results are reproducible off the free-tier firehose?

---

## Week 5 (24–30 August 2026)

**Hours:** ~16

### Planned this week

- Implement the approved architecture: backend pipeline + live dashboard.
- Make every layer visible (process-per-parameter timeline).
- Add system health so missing keys degrade a layer instead of crashing the demo.
- Run a real article and fix whatever the process log shows is broken.

### Work completed

**24 August — first working pipeline**

- Built the FastAPI app: Pydantic run envelope, `POST /api/runs`, SSE event stream, in-memory run store, Vite proxy `/api` → port 8000.
- Implemented ingest (paste text and/or URL via trafilatura).
- Implemented all seven layers:
  1. Input / ingest
  2. Preprocess: claim extraction + independent NER, with LLM/NER disagreement forwarded
  3. Verification: Claude query planner + NewsAPI, Guardian, second aggregator, Google Fact Check, Wikipedia; existence vs type-coverage classification
  4. Evidence: DeBERTa MNLI + blinded Gemini + deterministic fusion (no authenticity verdict)
  5. Uncertainty / risk on structured scores
  6. Human editorial decision on the dashboard (`verified | misleading | manipulated | unsupported | unverifiable | needs_investigation`)
  7. Citation-backed documentation record
- Replaced the stub UI with URL + text input, live timeline, claim–evidence matrix, corroboration/uncertainty panels, and save-decision control.
- Added **System health**: live probe of keys, engines, services, and layer readiness (keys never displayed).
- Added structured API logging (layer, process, tool, status; secrets redacted).
- Commit `2a11e06` *added backend model* (~4.3k lines) and `4e3cfa3` *refined backend — incomplete (20%)* (health panel, logging, LLM/NER/NewsAPI hardening).

**30 August — layer coordination fixes (first live run)**

- Ran a live ABC URL (Nepal–Tibet floods / missing Australians). Pipeline completed, but Pre-process, Evidence, and Record showed **degraded**.
- Diagnosed from the process log (not from health, which still reported keys as working):
  1. **Preprocess:** OpenAI HTTP 429 insufficient quota; no cross-provider failover, so claim extraction fell back to heuristics.
  2. **Evidence:** Hugging Face still called the retired `api-inference.huggingface.co` URL; NLI collapsed to a dummy 0.55 neutral on every pair, so fusion could only report `single_source`.
  3. **Record / analyst:** Gemini 2.5 model id 404 and Claude timeouts at 25s.
- Fixes shipped in commit `fc13f64` *backend layer coordination fixes*:
  - Hugging Face Inference **router** client with legacy fallback (`hf_inference.py`)
  - Longer LLM/HF timeouts (`llm_timeout_s=90`, `hf_timeout_s=60`)
  - Cross-provider `chat_json_any` failover (OpenAI → Anthropic → Gemini for preprocess; Gemini → Claude for evidence analyst and documentation)
  - Current Gemini model fallbacks; NLI fallback to BART MNLI then lexical overlap
  - Failover and skipped tools recorded as uncertainty, not as a fake verdict

### Evidence

- Commits:
  - `2a11e06` (24 Aug) — backend model + dashboard wiring
  - `4e3cfa3` (24 Aug) — health, logging, incomplete hardening
  - `fc13f64` (30 Aug) — layer coordination / failover / HF router
- Live run against `abc.net.au` coverage of the Nepal disaster: ingest fetched title/domain; verification returned multiple independent outlets (Guardian, ABC, CNN, SBS, Al Jazeera, NPR, …); journalist decision still required.
- Process log showing the three failure modes above and the subsequent failover path.
- Dashboard: Authenticate tab (timeline + matrix) and System health tab (keys/layers).
- README: how to run API + dashboard, key caveats (aggregator coverage, snippets vs full articles, disagreement shown on purpose).

### Decisions and rationale

- **Graceful degradation over hard failure.** A missing or quota-exhausted provider must not stop the pipeline or imply the article is fake.
- **Health ≠ run quality.** Keys can be present while a model id, timeout, or retired HTTP endpoint still degrades a layer. The process log is the source of truth for a run.
- **Cross-provider failover still preserves pinning.** We try the pinned model first; failover is explicit in the trace (`skipped` / failover events) so the thesis claim stays auditable.
- **Lexical NLI is a last resort.** If HF MNLI is down, we do not invent 0.55-neutral dummy scores and pretend DeBERTa ran.
- **Human decision is never auto-committed.** Even when uncertainty suggests `needs_investigation`, the journalist must save the outcome.

### Problems and blockers

- **OpenAI credits exhausted** during the live demo; preprocess now fails over, but the preferred GPT-4.1 extractor is off until billing is restored.
- **Hugging Face Inference API** moved; DeBERTa-quality stance labels depend on the new router actually serving the MNLI model. If it does not, evidence analysis is weaker than the thesis design.
- **NewsAPI / aggregator free tiers:** rate limits, recency windows, and snippets (not full text) cap how strong NLI can be.
- **Timeouts on long Gemini/Claude calls** still possible on large claim×evidence sets even after raising the limit to 90s.
- Health panel can report a layer “ready” (key present) while a given run is degraded — slightly confusing in a supervisor demo.

### Reflection

Week 5 is the first week the prototype *is* the framework rather than a mock. The Nepal live run was more valuable than a green health check: it showed that “keys configured” is not the same as “layers producing the evidence the thesis describes.” The main research-facing outcome is still intact: the system collected corroborating coverage, refused to emit true/false, and left the editorial decision on the dashboard. The engineering lesson is that heterogeneous engines need heterogeneous *failure* paths, or the design collapses back to a single heuristic.

### Next steps

- Re-run the same ABC (and 1–2 contrast) cases after failover; confirm Pre-process / Evidence / Record are `ok` or honestly `skipped`, not silently dummy-scored.
- Restore or replace the OpenAI preprocess path; confirm HF NLI returns non-neutral distributions on real pairs.
- Freeze 3–5 thesis demo cases (true coverage, single-source, contested, rumour) with notes on what the pipeline is expected to show.
- Tighten the health panel so “ready” reflects last successful engine call, not only key presence.
- Start the Week 6 write-up: limitations of aggregators, snippet NLI, and why disagreement is a feature.

### Questions for supervisor

- For the Thesis B demo, is a degraded-but-complete run (heuristic claims, lexical NLI, template documentation) acceptable, or do you want all pinned engines green before we present?
- Should publication-risk / recommended decision stay visible to the journalist, or only the evidence matrix + uncertainty list (to avoid nudging the human)?
- How should we evaluate the prototype academically — qualitative walkthroughs of Table 4.1 cases, or also inter-rater agreement between journalists using the dashboard?
- Is it in scope this session to add even a thin media/provenance hook (C2PA / reverse image), or stay text/URL-only for the remainder of Thesis B?
- Given OpenAI quota and HF endpoint churn, are you comfortable with documented failover as part of the contribution (robust decision-support) rather than treating it as an implementation defect?
