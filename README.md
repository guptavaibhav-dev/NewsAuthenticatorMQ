# NewsAuth

Thesis B prototype for *A Framework for Authenticating News Content* (COMP4092, Macquarie University).

The dashboard is a journalist-centred decision-support system. It collects evidence through a 7-layer pipeline and **does not emit a true/false verdict**. The journalist records the editorial decision.

## Architecture

1. Input (text and/or URL)
2. Pre-processing and Classification — GPT-4.1 + independent NER
3. Verification Tool Layer — Claude query planner + NewsAPI, Guardian, GNews/NewsData, Google Fact Check, Wikipedia
4. Evidence Analysis — DeBERTa MNLI + blinded Gemini 2.5 Pro + deterministic fusion
5. Uncertainty and Risk Assessment — conservative OpenAI model on structured scores only
6. Human Editorial Decision — dashboard only
7. Output and Documentation — citation-backed record

## Run

Terminal 1 — API:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# fill in the keys you have; missing keys skip that engine/tool
python -m uvicorn app.main:app --reload --port 8000
```

Terminal 2 — dashboard:

```bash
npm install
npm run dev
```

Open http://localhost:5173/ — Vite proxies `/api` to the FastAPI server.

Watch the **API terminal** for pipeline logs: layer steps, skipped tools, LLM calls, and errors. Keys are redacted. Set `LOG_LEVEL=DEBUG` in `backend/.env` for HTTP request traces.

## Keys

See [`backend/.env.example`](backend/.env.example). You do not need every key for a demo: the pipeline completes with skipped tools recorded as uncertainty, not as “fake”.

Useful free/developer keys:

- [NewsAPI](https://newsapi.org/)
- [Guardian Open Platform](https://open-platform.theguardian.com/access/)
- [Google Fact Check Tools](https://developers.google.com/fact-check/tools/api) (Google API key)
- OpenAI, Anthropic, Gemini for the heterogeneous LLM layers
- Hugging Face token for hosted DeBERTa / embeddings / NER (optional; lexical fallbacks exist)

## Notes

- Aggregator APIs cover a subset of the web and recency windows on free tiers.
- Snippets are not full articles; NLI can miss context.
- Multi-engine disagreement is shown on purpose.

## Future work

- **Media provenance (not wired).** `backend/app/tools/media.py` documents the intended C2PA / Content Credentials and reverse-image-search design. Layer 1 does not call it: a skipped media stub is noise, and a missing credential must not be treated as falsity.
