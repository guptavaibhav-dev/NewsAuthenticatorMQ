"""Shared helpers for NewsAuth Excalidraw architecture diagrams."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

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
PAPER = "#f8f9fa"

FONT = 2
LINE_HEIGHT = 1.25
NOW = 1773320000000
LAYERS = [
    "1 Input",
    "2 Pre-process",
    "3 Verification",
    "4 Evidence",
    "5 Uncertainty",
    "6 Editorial",
    "7 Record",
]


class Diagram:
    def __init__(self) -> None:
        self.elements: list[dict] = []
        self.boxes: dict[str, dict] = {}
        self._n = 0
        self._bindings: dict[str, list[dict]] = {}

    def _idx(self) -> str:
        i = self._n
        self._n += 1
        return f"{chr(ord('a') + i // 10)}{i % 10}"

    def _seed(self, key: str) -> int:
        return int(hashlib.md5(key.encode()).hexdigest()[:8], 16) % 2_147_483_647

    def _nonce(self, key: str) -> int:
        return int(hashlib.md5(f"n:{key}".encode()).hexdigest()[:8], 16) % 2_147_483_647

    def _base(self, eid: str, typ: str, x: float, y: float, w: float, h: float, **extra) -> dict:
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
            "index": self._idx(),
            "roundness": extra.pop(
                "roundness", {"type": 3} if typ in {"rectangle", "ellipse"} else None
            ),
            "seed": self._seed(eid),
            "version": 1,
            "versionNonce": self._nonce(eid),
            "isDeleted": False,
            "boundElements": None,
            "updated": NOW,
            "link": extra.pop("link", None),
            "locked": False,
        }
        el.update(extra)
        return el

    def measure(self, text: str, size: float) -> tuple[float, float]:
        lines = text.split("\n") or [""]
        width = max((len(line) for line in lines), default=1) * size * 0.58
        height = max(len(lines), 1) * size * LINE_HEIGHT
        return width, height

    def wrap(self, text: str, max_chars: int) -> str:
        if max_chars < 8:
            max_chars = 8
        out: list[str] = []
        for raw in text.split("\n"):
            cur = ""
            for word in raw.split(" "):
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

    def add(self, el: dict) -> dict:
        self.elements.append(el)
        return el

    def text(
        self,
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
            wrapped = self.wrap(content, int(width / (size * 0.58)))
            _w, h = self.measure(wrapped, size)
            w = width
        else:
            w, h = self.measure(wrapped, size)
        el = self._base(
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
            self._bindings.setdefault(container, []).append({"id": eid, "type": "text"})
        return self.add(el)

    def box(
        self,
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
        rect = self.add(
            self._base(
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
        self.boxes[key] = {"x": x, "y": y, "w": w, "h": h, "id": key}
        pad = 16
        if body:
            title_el = self.text(
                f"{key}-title",
                x + pad,
                y + 12,
                title,
                size=title_size,
                group=[gid],
                width=w - pad * 2,
            )
            self.text(
                f"{key}-body",
                x + pad,
                y + 12 + title_el["height"] + 6,
                body,
                size=body_size,
                color="#343a40",
                group=[gid],
                width=w - pad * 2,
            )
        else:
            _tw, th = self.measure(title, title_size)
            self.text(
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

    def diamond(
        self, key: str, x: float, y: float, w: float, h: float, label: str, *, fill: str = YELLOW
    ) -> dict:
        gid = f"g-{key}"
        el = self.add(
            self._base(
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
        self.boxes[key] = {"x": x, "y": y, "w": w, "h": h, "id": key}
        _tw, th = self.measure(label, 16)
        self.text(
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

    def chip(self, key: str, x: float, y: float, w: float, h: float, label: str, *, active: bool) -> None:
        self.box(
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

    def pipeline_chips(self, x: float, y: float, active: int) -> None:
        self.text("pipe-label", x, y - 24, "Place in the 7-layer pipeline", size=13, color="#495057")
        cx = x
        for i, label in enumerate(LAYERS):
            self.chip(f"chip-{i}", cx, y, 168, 40, label, active=(i + 1) == active)
            cx += 180

    def frame(self, key: str, x: float, y: float, w: float, h: float, title: str, *, fill: str = PAPER) -> None:
        self.add(
            self._base(
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
        self.text(f"{key}-title", x + 16, y + 10, title, size=15, color="#495057")

    def _anchor(self, box_id: str, side: str) -> tuple[float, float]:
        b = self.boxes[box_id]
        cx = b["x"] + b["w"] / 2
        cy = b["y"] + b["h"] / 2
        return {
            "top": (cx, b["y"]),
            "bottom": (cx, b["y"] + b["h"]),
            "left": (b["x"], cy),
            "right": (b["x"] + b["w"], cy),
        }[side]

    def arrow(
        self,
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
        drop: bool | str = False,
    ) -> None:
        x1, y1 = self._anchor(src, src_side)
        x2, y2 = self._anchor(dst, dst_side)
        if drop in (True, "src"):
            x2 = x1
        elif drop == "dst":
            x1 = x2
        if elbow == "hv":
            points = [[0, 0], [x2 - x1, 0], [x2 - x1, y2 - y1]]
        elif elbow == "vh":
            points = [[0, 0], [0, y2 - y1], [x2 - x1, y2 - y1]]
        elif elbow == "vhv":
            mid_y = (y1 + y2) / 2
            points = [[0, 0], [0, mid_y - y1], [x2 - x1, mid_y - y1], [x2 - x1, y2 - y1]]
        else:
            points = [[0, 0], [x2 - x1, y2 - y1]]
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        el = self._base(
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
            startBinding={"elementId": src, "focus": 0, "gap": 8},
            endBinding={"elementId": dst, "focus": 0, "gap": 8},
            startArrowhead=None,
            endArrowhead="arrow",
            elbowed=False,
            points=points,
            lastCommittedPoint=None,
        )
        self.add(el)
        self._bindings.setdefault(src, []).append({"id": eid, "type": "arrow"})
        self._bindings.setdefault(dst, []).append({"id": eid, "type": "arrow"})
        if label:
            mx = x1 + (points[0][0] + points[-1][0]) / 2
            my = y1 + (points[0][1] + points[-1][1]) / 2
            tw, th = self.measure(label, 13)
            self.text(f"{eid}-label", mx - tw / 2, my - th - 6, label, size=13, color="#495057")

    def header(self, title: str, subtitle: str) -> None:
        self.text("title", 60, 28, title, size=28)
        self.text("subtitle", 60, 70, subtitle, size=15, color="#495057", width=1880)

    def write(self, path: Path) -> None:
        by_id = {el["id"]: el for el in self.elements}
        for eid, bound in self._bindings.items():
            if eid in by_id:
                by_id[eid]["boundElements"] = bound
        data = {
            "type": "excalidraw",
            "version": 2,
            "source": "https://excalidraw.com",
            "elements": self.elements,
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
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"Wrote {path} ({len(self.elements)} elements)")
