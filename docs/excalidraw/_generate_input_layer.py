"""Generate docs/excalidraw/01-input-layer.excalidraw from the implemented Input layer."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

OUT = Path(__file__).with_name("01-input-layer.excalidraw")

STROKE = "#1e1e1e"
WHITE = "#ffffff"
BLUE = "#a5d8ff"
PALE_BLUE = "#d0ebff"
GREEN = "#b2f2bb"
YELLOW = "#ffec99"
ORANGE = "#ffd8a8"
RED = "#ffc9c9"
GRAY = "#e9ecef"
VIOLET = "#d0bfff"
MUTED = "#868e96"

FONT = 2  # Helvetica — readable for thesis diagrams
LINE_HEIGHT = 1.25
NOW = 1773320000000

elements: list[dict] = []
boxes: dict[str, dict] = {}
_n = 0
_bindings: dict[str, list[dict]] = {}


def _idx() -> str:
    global _n
    i = _n
    _n += 1
    return f"{chr(ord('a') + i // 10)}{i % 10}"


def _seed(key: str) -> int:
    return int(hashlib.md5(key.encode()).hexdigest()[:8], 16) % 2_147_483_647


def _nonce(key: str) -> int:
    return int(hashlib.md5(f"n:{key}".encode()).hexdigest()[:8], 16) % 2_147_483_647


def _base(eid: str, typ: str, x: float, y: float, w: float, h: float, **extra) -> dict:
    el = {
        "id": eid,
        "type": typ,
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "angle": 0,
        "strokeColor": extra.pop("strokeColor", STROKE),
        "backgroundColor": extra.pop("backgroundColor", WHITE),
        "fillStyle": extra.pop("fillStyle", "solid"),
        "strokeWidth": extra.pop("strokeWidth", 2),
        "strokeStyle": extra.pop("strokeStyle", "solid"),
        "roughness": extra.pop("roughness", 1),
        "opacity": 100,
        "groupIds": extra.pop("groupIds", []),
        "frameId": extra.pop("frameId", None),
        "index": _idx(),
        "roundness": extra.pop("roundness", {"type": 3} if typ in {"rectangle", "ellipse"} else None),
        "seed": _seed(eid),
        "version": 1,
        "versionNonce": _nonce(eid),
        "isDeleted": False,
        "boundElements": None,
        "updated": NOW,
        "link": extra.pop("link", None),
        "locked": False,
    }
    el.update(extra)
    return el


def measure(text: str, size: float) -> tuple[float, float]:
    lines = text.split("\n") or [""]
    width = max((len(line) for line in lines), default=1) * size * 0.58
    height = max(len(lines), 1) * size * LINE_HEIGHT
    return width, height


def wrap(text: str, max_chars: int) -> str:
    if max_chars < 8:
        max_chars = 8
    out: list[str] = []
    for raw in text.split("\n"):
        words = raw.split(" ")
        cur = ""
        for word in words:
            trial = word if not cur else f"{cur} {word}"
            if len(trial) <= max_chars:
                cur = trial
            else:
                if cur:
                    out.append(cur)
                cur = word
        if cur:
            out.append(cur)
    return "\n".join(out) if out else text


def add(el: dict) -> dict:
    elements.append(el)
    return el


def text(
    eid: str,
    x: float,
    y: float,
    content: str,
    *,
    size: float = 16,
    align: str = "left",
    color: str = STROKE,
    width: float | None = None,
    group: list[str] | None = None,
    container: str | None = None,
    valign: str = "top",
) -> dict:
    wrapped = content
    if width is not None:
        max_chars = int(width / (size * 0.58))
        wrapped = wrap(content, max_chars)
        w, h = measure(wrapped, size)
        w = width
    else:
        w, h = measure(wrapped, size)
    el = _base(
        eid,
        "text",
        x,
        y,
        w,
        h,
        backgroundColor="transparent",
        strokeColor=color,
        roundness=None,
        groupIds=group or [],
    )
    el.update(
        {
            "text": wrapped,
            "originalText": content,
            "fontSize": size,
            "fontFamily": FONT,
            "textAlign": align,
            "verticalAlign": valign,
            "containerId": container,
            "autoResize": width is None,
            "lineHeight": LINE_HEIGHT,
        }
    )
    if container:
        _bindings.setdefault(container, []).append({"id": eid, "type": "text"})
    return add(el)


def box(
    key: str,
    x: float,
    y: float,
    w: float,
    h: float,
    title: str,
    body: str = "",
    *,
    fill: str = WHITE,
    stroke: str = STROKE,
    dashed: bool = False,
    title_size: float = 16,
    body_size: float = 14,
) -> dict:
    gid = f"g-{key}"
    rect = add(
        _base(
            key,
            "rectangle",
            x,
            y,
            w,
            h,
            backgroundColor=fill,
            strokeColor=stroke,
            strokeStyle="dashed" if dashed else "solid",
            groupIds=[gid],
        )
    )
    boxes[key] = {"x": x, "y": y, "w": w, "h": h, "id": key}
    pad = 14
    if body:
        title_el = text(
            f"{key}-title",
            x + pad,
            y + 10,
            title,
            size=title_size,
            group=[gid],
            width=w - pad * 2,
        )
        text(
            f"{key}-body",
            x + pad,
            y + 10 + title_el["height"] + 4,
            body,
            size=body_size,
            color="#343a40",
            group=[gid],
            width=w - pad * 2,
        )
    else:
        _tw, th = measure(title, title_size)
        text(
            f"{key}-title",
            x + pad,
            y + (h - th) / 2,
            title,
            size=title_size,
            align="center",
            group=[gid],
            width=w - pad * 2,
        )
    return rect


def diamond(key: str, x: float, y: float, w: float, h: float, label: str, *, fill: str = YELLOW) -> dict:
    gid = f"g-{key}"
    el = add(
        _base(
            key,
            "diamond",
            x,
            y,
            w,
            h,
            backgroundColor=fill,
            roundness=None,
            groupIds=[gid],
        )
    )
    boxes[key] = {"x": x, "y": y, "w": w, "h": h, "id": key}
    _tw, th = measure(label, 16)
    text(
        f"{key}-label",
        x + w * 0.15,
        y + (h - th) / 2,
        label,
        size=16,
        align="center",
        group=[gid],
        width=w * 0.7,
    )
    return el


def chip(key: str, x: float, y: float, w: float, h: float, label: str, *, active: bool) -> None:
    box(
        key,
        x,
        y,
        w,
        h,
        label,
        fill=BLUE if active else WHITE,
        stroke=STROKE if active else MUTED,
        title_size=14,
    )


def frame(key: str, x: float, y: float, w: float, h: float, title: str, *, fill: str = "#f8f9fa") -> None:
    add(
        _base(
            key,
            "rectangle",
            x,
            y,
            w,
            h,
            backgroundColor=fill,
            strokeColor="#adb5bd",
            strokeWidth=1,
            roundness={"type": 3},
        )
    )
    text(f"{key}-title", x + 16, y + 10, title, size=15, color="#495057")


def _anchor(box_id: str, side: str) -> tuple[float, float]:
    b = boxes[box_id]
    cx = b["x"] + b["w"] / 2
    cy = b["y"] + b["h"] / 2
    return {
        "top": (cx, b["y"]),
        "bottom": (cx, b["y"] + b["h"]),
        "left": (b["x"], cy),
        "right": (b["x"] + b["w"], cy),
    }[side]


def arrow(
    eid: str,
    src: str,
    dst: str,
    *,
    src_side: str = "bottom",
    dst_side: str = "top",
    label: str = "",
    color: str = STROKE,
    dashed: bool = False,
    elbow: str | None = None,
) -> None:
    x1, y1 = _anchor(src, src_side)
    x2, y2 = _anchor(dst, dst_side)
    if elbow == "hv":
        mid_x = x2
        points = [[0, 0], [mid_x - x1, 0], [mid_x - x1, y2 - y1]]
    elif elbow == "vh":
        mid_y = y2
        points = [[0, 0], [0, mid_y - y1], [x2 - x1, mid_y - y1]]
    elif elbow == "vhv":
        mid_y = (y1 + y2) / 2
        points = [[0, 0], [0, mid_y - y1], [x2 - x1, mid_y - y1], [x2 - x1, y2 - y1]]
    else:
        points = [[0, 0], [x2 - x1, y2 - y1]]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    el = _base(
        eid,
        "arrow",
        x1,
        y1,
        max(xs) - min(xs),
        max(ys) - min(ys),
        backgroundColor="transparent",
        strokeColor=color,
        strokeStyle="dashed" if dashed else "solid",
        roundness={"type": 2},
        startBinding={"elementId": src, "focus": 0, "gap": 6},
        endBinding={"elementId": dst, "focus": 0, "gap": 6},
        startArrowhead=None,
        endArrowhead="arrow",
        elbowed=False,
        points=points,
        lastCommittedPoint=None,
    )
    add(el)
    _bindings.setdefault(src, []).append({"id": eid, "type": "arrow"})
    _bindings.setdefault(dst, []).append({"id": eid, "type": "arrow"})
    if label:
        mx = x1 + (points[0][0] + points[-1][0]) / 2
        my = y1 + (points[0][1] + points[-1][1]) / 2
        tw, th = measure(label, 12)
        text(f"{eid}-label", mx - tw / 2, my - th - 4, label, size=12, color="#495057")


def apply_bindings() -> None:
    by_id = {el["id"]: el for el in elements}
    for eid, bound in _bindings.items():
        if eid in by_id:
            by_id[eid]["boundElements"] = bound


def build() -> dict:
    # Header
    text(
        "title",
        80,
        36,
        "Layer 1 — Input (content intake)",
        size=28,
    )
    text(
        "subtitle",
        80,
        76,
        "NewsAuth · Thesis B · COMP4092    Deterministic ingest. No LLM. Captures journalist text and/or a public URL into InputPayload. Does not judge authenticity.",
        size=14,
        color="#495057",
        width=2000,
    )

    # Pipeline context
    text("pipe-label", 80, 118, "Place in the 7-layer pipeline", size=13, color="#495057")
    labels = [
        ("1 Input", True),
        ("2 Pre-process", False),
        ("3 Verification", False),
        ("4 Evidence", False),
        ("5 Uncertainty", False),
        ("6 Editorial", False),
        ("7 Record", False),
    ]
    x = 80
    for i, (label, active) in enumerate(labels):
        chip(f"chip-{i}", x, 142, 168, 40, label, active=active)
        x += 180

    # 1. Journalist surface
    frame("f-ui", 60, 210, 2120, 168, "1. Journalist surface  ·  src/App.tsx")
    box(
        "ui-url",
        84,
        248,
        620,
        108,
        "Article URL",
        "Optional public URL.\nPlaceholder https://…",
        fill=PALE_BLUE,
    )
    box(
        "ui-text",
        724,
        248,
        720,
        108,
        "News content",
        "Paste a headline, claim, or article body.\nEither field is enough to run.",
        fill=PALE_BLUE,
    )
    box(
        "ui-run",
        1464,
        248,
        340,
        108,
        "Run verification",
        "Enabled when text OR url is non-empty.\nPOST /api/runs { text, url }",
        fill=GREEN,
    )
    box(
        "ui-clear",
        1824,
        248,
        332,
        108,
        "Clear",
        "Resets fields, run envelope,\nand inspector chat.",
        fill=GRAY,
    )

    # 2. API gate
    frame("f-api", 60, 404, 1040, 168, "2. API gate  ·  src/lib/api.ts  →  POST /api/runs  ·  backend/app/main.py")
    box(
        "api-validate",
        84,
        442,
        480,
        108,
        "Reject empty intake",
        "HTTP 400 if both text and url are blank:\n“Provide article text, a URL, or both.”",
        fill=ORANGE,
    )
    box(
        "api-create",
        584,
        442,
        492,
        108,
        "create_run",
        "Mint run_id · queue RunEnvelope\nstore original_text / original_url\nexecute_layer(1) immediately",
        fill=BLUE,
    )

    frame("f-store", 1124, 404, 1056, 168, "3. Run envelope  ·  pipeline/store.py")
    box(
        "store-state",
        1148,
        442,
        500,
        108,
        "RunState",
        "Persists original paste + URL separately\nfrom extracted body, so re-run can restore.",
        fill=PALE_BLUE,
    )
    box(
        "store-snap",
        1668,
        442,
        488,
        108,
        "Layer snapshot",
        "take_snapshot(1) before work.\nRe-run restores this snapshot, then ingest again.",
        fill=PALE_BLUE,
    )

    # 4. Orchestrator
    frame("f-orch", 60, 598, 2120, 168, "4. Orchestrator  ·  pipeline/orchestrator.py  _run_input")
    box(
        "orch-trace",
        84,
        636,
        400,
        108,
        "Emit trace",
        "layer=input · tool=ingest\nprocess=content intake (running)\nparameter=text_or_url",
        fill=VIOLET,
    )
    box(
        "orch-ingest",
        504,
        636,
        400,
        108,
        "ingest_input()",
        "tools/ingest.py\nAlways runs. HTTP only if a URL\nwas supplied.",
        fill=BLUE,
    )
    box(
        "orch-guard",
        924,
        636,
        420,
        108,
        "Empty-text guard",
        "If raw_text is still blank → ValueError.\nPaste content or a reachable URL.\nRun phase = error.",
        fill=RED,
    )
    box(
        "orch-media",
        1364,
        636,
        400,
        108,
        "inspect_media()",
        "tools/media.py\nAlways skipped in v1.\nC2PA / reverse-image reserved.",
        fill=GRAY,
        dashed=True,
    )
    box(
        "orch-engine",
        1784,
        636,
        372,
        108,
        "engines_used",
        'input = "ingest"\nNo model is called in this layer.',
        fill=GREEN,
    )
    arrow("a-ui-api", "ui-run", "api-create")
    arrow("a-api-orch", "api-create", "orch-ingest")
    arrow("a-tr-ing", "orch-trace", "orch-ingest", src_side="right", dst_side="left")
    arrow("a-ing-guard", "orch-ingest", "orch-guard", src_side="right", dst_side="left")
    arrow("a-guard-media", "orch-guard", "orch-media", src_side="right", dst_side="left")
    arrow("a-media-eng", "orch-media", "orch-engine", src_side="right", dst_side="left")

    # 5. Decision
    diamond("d-url", 900, 800, 280, 150, "URL\nprovided?")
    arrow("a-orch-d", "orch-ingest", "d-url")

    # Text-only path
    frame("f-text", 60, 990, 700, 420, "5a. Text-only path  ·  no HTTP")
    box(
        "txt-skip",
        84,
        1028,
        652,
        130,
        "fetch_status = skipped",
        "No GET. canonical_url and publisher_domain stay empty.\nextracted_char_count = 0 · text_merged = false.",
        fill=GRAY,
    )
    box(
        "txt-raw",
        84,
        1174,
        652,
        130,
        "raw_text = pasted content",
        "Strip whitespace. This string is what Layer 2 classifies.\nIf paste is also empty, the empty-text guard fails the run.",
        fill=GREEN,
    )
    box(
        "txt-note",
        84,
        1320,
        652,
        68,
        "Use this path for claims, headlines, and social copy with no permalink.",
        fill=WHITE,
        title_size=14,
    )

    # URL path
    frame("f-url", 800, 990, 1380, 420, "5b. URL fetch path  ·  tools/ingest.py  +  scoring/urls.py")
    box(
        "url-get",
        824,
        1028,
        420,
        150,
        "HTTP GET",
        "follow_redirects = true\nUser-Agent: NewsAuthBot/1.0\nAccept: text/html\nRecords fetch_timestamp (UTC)",
        fill=PALE_BLUE,
    )
    box(
        "url-traf",
        1264,
        1028,
        420,
        150,
        "trafilatura extract",
        "JSON output: title + text\ncomments/tables off\nEXTRACTION_TIMEOUT = 20s",
        fill=BLUE,
    )
    box(
        "url-fb",
        1704,
        1028,
        452,
        150,
        "Fallbacks",
        "Title: og:title → twitter:title → <title>\nBody: trafilatura.extract() plain\nGeneric “BBC News” titles ignored",
        fill=ORANGE,
    )
    box(
        "url-norm",
        824,
        1190,
        420,
        196,
        "Normalize identity",
        "canonical_url: strip www + trailing /\npublisher_domain: eTLD+1 via tldextract\n(bbc.com and bbc.co.uk stay distinct hosts;\nindependence is a later-layer concern)",
        fill=PALE_BLUE,
    )
    box(
        "url-merge",
        1264,
        1190,
        420,
        196,
        "Merge pasted + fetched",
        "If paste is non-empty and not already\ninside the fetched body, prepend it.\ntext_merged = true in that case.\nOtherwise keep fetched body only.",
        fill=VIOLET,
    )
    box(
        "url-status",
        1704,
        1190,
        452,
        196,
        "fetch_status",
        "ok — extracted body is non-empty\nempty — HTTP success, no article text\nerror — HTTP failure or exception\nOn error, keep the journalist’s paste.\nNever treat a failed fetch as “fake”.",
        fill=YELLOW,
    )

    arrow("a-d-no", "d-url", "txt-skip", src_side="left", dst_side="top", label="no")
    arrow("a-d-yes", "d-url", "url-get", src_side="right", dst_side="top", label="yes")
    arrow("a-t1", "txt-skip", "txt-raw")
    arrow("a-t2", "txt-raw", "txt-note")
    arrow("a-u1", "url-get", "url-traf", src_side="right", dst_side="left")
    arrow("a-u2", "url-traf", "url-fb", src_side="right", dst_side="left")
    arrow("a-u3", "url-get", "url-norm")
    arrow("a-u4", "url-traf", "url-merge")
    arrow("a-u5", "url-fb", "url-status")

    box(
        "merge",
        820,
        1428,
        440,
        64,
        "Both paths write envelope.input",
        fill=YELLOW,
        title_size=15,
    )

    # InputPayload
    frame("f-out", 60, 1516, 1480, 310, "6. Output written onto the run envelope  ·  schemas/envelope.py  InputPayload")
    box(
        "out-payload",
        84,
        1554,
        1432,
        250,
        "envelope.input",
        "raw_text                 body Layer 2 will classify\n"
        "url                      journalist-supplied URL (or null)\n"
        "fetched_title            extracted headline, if any\n"
        "canonical_url            normalized final URL after redirects\n"
        "publisher_domain         registrable domain (eTLD+1)\n"
        "fetch_timestamp          UTC ISO-8601 when the GET started\n"
        "fetch_status             ok | empty | error | skipped\n"
        "fetch_error              truncated exception / HTTP code\n"
        "extracted_char_count     fetched body length (0 if skipped)\n"
        "text_merged              paste prepended to fetched body",
        fill=GREEN,
        body_size=15,
    )

    # Inspector + gate
    frame("f-ui2", 1564, 1516, 616, 310, "7. What the journalist sees  ·  layerOutputs.tsx")
    box(
        "insp",
        1588,
        1554,
        568,
        250,
        "Inspector — Layer 1 card",
        "Resolved URL\nPublisher domain\nFetch status + timestamp\nExtracted headline\nExtracted body (char count)\nPasted text merged? yes/no\nMedia-provenance hook: skipped\nFetch error, if any",
        fill=PALE_BLUE,
        body_size=14,
    )

    # Pause / next layer
    frame("f-gate", 60, 1852, 1480, 170, "8. Human gate  ·  the pipeline pauses here")
    box(
        "gate-pause",
        84,
        1890,
        520,
        110,
        "phase = awaiting_decision",
        "Layer 1 is complete. Nothing else runs\nuntil the journalist chooses.",
        fill=YELLOW,
    )
    box(
        "gate-acts",
        624,
        1890,
        520,
        110,
        "Proceed  ·  Re-run  ·  Ask",
        "Proceed → Layer 2 classification\nRe-run restores snapshot, ingest again\nAsk answers from this layer’s output only",
        fill=ORANGE,
    )
    box(
        "gate-l2",
        1164,
        1890,
        352,
        110,
        "Next: Layer 2",
        "Pre-processing and\nClassification\nGPT-4.1 + independent NER",
        fill=BLUE,
    )

    frame("f-not", 1564, 1852, 616, 170, "This layer does not")
    box(
        "not-do",
        1588,
        1890,
        568,
        110,
        "No classification, retrieval, or verdict",
        "Does not extract claims, call news APIs,\nrun NLI, or score authenticity. Failed or\nempty fetches are coverage gaps, not “fake”.",
        fill=RED,
        title_size=15,
        body_size=13,
    )

    arrow("a-txt-out", "txt-note", "merge", src_side="bottom", dst_side="left")
    arrow("a-url-out", "url-status", "merge", src_side="bottom", dst_side="right")
    arrow("a-merge-out", "merge", "out-payload")
    arrow("a-out-insp", "out-payload", "insp", src_side="right", dst_side="left")
    arrow("a-out-gate", "out-payload", "gate-pause")
    arrow("a-g1", "gate-pause", "gate-acts", src_side="right", dst_side="left")
    arrow("a-g2", "gate-acts", "gate-l2", src_side="right", dst_side="left")

    # Legend
    text("leg-h", 80, 2046, "fetch_status legend  ·  ToolStatus in the envelope", size=15)
    box("leg-ok", 80, 2080, 240, 56, "ok — body extracted", fill=GREEN, title_size=13)
    box("leg-empty", 340, 2080, 280, 56, "empty — page had no article text", fill=YELLOW, title_size=13)
    box("leg-err", 640, 2080, 300, 56, "error — HTTP/network failure; paste kept", fill=RED, title_size=13)
    box("leg-skip", 960, 2080, 280, 56, "skipped — no URL supplied", fill=GRAY, title_size=13)
    box("leg-media", 1260, 2080, 400, 56, "media hook — skipped (later iteration)", fill=WHITE, dashed=True, title_size=13)
    box("leg-engine", 1680, 2080, 500, 56, "Engine: ingest (deterministic)  ·  no API key", fill=VIOLET, title_size=13)

    text(
        "footer",
        80,
        2156,
        "Source of truth: backend/app/tools/ingest.py, backend/app/pipeline/orchestrator.py (_run_input), backend/app/schemas/envelope.py (InputPayload), src/App.tsx, src/components/layerOutputs.tsx.",
        size=12,
        color="#868e96",
        width=2100,
    )

    apply_bindings()
    return {
        "type": "excalidraw",
        "version": 2,
        "source": "https://excalidraw.com",
        "elements": elements,
        "appState": {
            "gridSize": 20,
            "gridModeEnabled": False,
            "viewBackgroundColor": "#ffffff",
            "currentItemFontFamily": FONT,
            "currentItemStrokeColor": STROKE,
            "currentItemBackgroundColor": PALE_BLUE,
        },
        "files": {},
    }


def main() -> None:
    data = build()
    OUT.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Wrote {OUT} ({len(data['elements'])} elements)")


if __name__ == "__main__":
    main()
