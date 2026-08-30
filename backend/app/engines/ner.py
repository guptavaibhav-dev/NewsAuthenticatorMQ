from __future__ import annotations

import re
from datetime import datetime

import httpx

from app.config import Settings
from app.engines.hf_inference import hf_infer
from app.logutil import get_logger, short_error
from app.schemas.envelope import Entity, EntityType

log = get_logger("ner")

_DATE = re.compile(
    r"\b(?:\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}"
    r"|\d{4}-\d{2}-\d{2}"
    r"|(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},?\s+\d{4})\b",
    re.I,
)
_PROPER = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b")
_STOP = {
    "The",
    "A",
    "An",
    "This",
    "That",
    "These",
    "Those",
    "In",
    "On",
    "At",
    "For",
    "And",
    "But",
    "He",
    "She",
    "We",
    "They",
    "It",
    "His",
    "Her",
    "If",
    "There",
    "Since",
    "News",
    "Asked",
    "No",
    "Let",
    "May",
    "My",
    "Our",
    "Your",
    "Not",
    "After",
    "Last",
    "Experts",
    "Democracy",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
}
_STOP_LOWER = {s.lower() for s in _STOP} | {
    "we", "if", "there", "it", "his", "since", "news", "asked", "no", "let",
    "may", "he", "she", "they", "experts", "democracy", "my", "our", "your",
}


class NerEngine:
    """Independent NER (spaCy if present, else HF token-class, else heuristics)."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client
        self.engine_name = "heuristic-ner"

    async def extract(self, text: str) -> list[Entity]:
        sample = text[:4000]
        if self.settings.hf_token:
            try:
                entities = await self._hf_ner(sample)
                if entities:
                    self.engine_name = f"hf:{self.settings.ner_model}"
                    return entities
            except Exception as exc:
                log.warning("hf ner failed: %s", short_error(exc))
        try:
            entities = _spacy_ner(sample)
            if entities:
                self.engine_name = "spacy"
                return entities
        except Exception:
            pass
        self.engine_name = "heuristic-ner"
        return heuristic_ner(sample)

    async def _hf_ner(self, text: str) -> list[Entity]:
        timeout_s = float(getattr(self.settings, "hf_timeout_s", 60.0) or 60.0)
        payload = await hf_infer(
            self.client,
            self.settings.hf_token,
            self.settings.ner_model,
            {"inputs": text, "options": {"wait_for_model": True}},
            timeout_s=timeout_s,
        )
        if not isinstance(payload, list):
            return []
        if payload and isinstance(payload[0], list):
            payload = [row for group in payload for row in group if isinstance(row, dict)]
        mapped: list[Entity] = []
        seen: set[tuple[str, str]] = set()
        for row in payload:
            if not isinstance(row, dict):
                continue
            word = str(row.get("word") or row.get("entity_group") or "").strip()
            label = str(row.get("entity_group") or row.get("entity") or "").upper()
            etype = _map_ner_label(label)
            key = (word.lower(), etype)
            if not word or key in seen:
                continue
            seen.add(key)
            mapped.append(Entity(text=word, type=etype, source="ner"))
        return mapped


def _map_ner_label(label: str) -> EntityType:
    if "PER" in label:
        return "PERSON"
    if "ORG" in label:
        return "ORG"
    if "LOC" in label or "GPE" in label or "MISC" in label:
        return "GPE"
    if "DATE" in label or "TIME" in label:
        return "DATE"
    if "EVENT" in label:
        return "EVENT"
    return "OTHER"


def _spacy_ner(text: str) -> list[Entity]:
    import spacy  # type: ignore

    try:
        nlp = spacy.load("en_core_web_sm")
    except Exception:
        nlp = spacy.blank("en")
        return []
    doc = nlp(text)
    out: list[Entity] = []
    seen: set[tuple[str, str]] = set()
    mapping = {
        "PERSON": "PERSON",
        "ORG": "ORG",
        "GPE": "GPE",
        "LOC": "GPE",
        "DATE": "DATE",
        "EVENT": "EVENT",
    }
    for ent in doc.ents:
        etype = mapping.get(ent.label_)
        if not etype:
            continue
        key = (ent.text.lower(), etype)
        if key in seen:
            continue
        seen.add(key)
        out.append(Entity(text=ent.text, type=etype, source="ner"))  # type: ignore[arg-type]
    return out


def heuristic_ner(text: str) -> list[Entity]:
    out: list[Entity] = []
    seen: set[str] = set()
    for match in _DATE.finditer(text):
        value = match.group(0)
        if value.lower() not in seen:
            seen.add(value.lower())
            out.append(Entity(text=value, type="DATE", source="ner"))
    for match in _PROPER.finditer(text):
        value = match.group(1)
        first = value.split()[0]
        if first in _STOP or first.lower() in _STOP_LOWER or value.lower() in _STOP_LOWER:
            continue
        if len(value.split()) == 1 and len(value) < 4:
            continue
        if value.lower() in seen:
            continue
        seen.add(value.lower())
        etype: EntityType = "ORG" if any(
            tok in value for tok in ("University", "Party", "Agency", "Ministry", "Corp")
        ) else "PERSON" if len(value.split()) >= 2 else "GPE"
        out.append(Entity(text=value, type=etype, source="ner"))
        if len(out) > 24:
            break
    return out


def parse_date_hint(text: str) -> datetime | None:
    match = _DATE.search(text or "")
    if not match:
        return None
    raw = match.group(0)
    for fmt in ("%Y-%m-%d", "%d %B %Y", "%B %d, %Y", "%d %b %Y"):
        try:
            return datetime.strptime(raw.replace(",", ""), fmt.replace(",", ""))
        except ValueError:
            continue
    return None
