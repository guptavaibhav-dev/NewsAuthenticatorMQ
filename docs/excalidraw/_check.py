"""Check a generated diagram: text fits its box, titles do not wrap, no overlaps."""

import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
els = {e["id"]: e for e in data["elements"]}
# Frames (f-*) are background containers; boxes are meant to sit inside them.
rects = {
    e["id"]: e
    for e in data["elements"]
    if e["type"] == "rectangle"
    and not e["id"].startswith("chip-")
    and not e["id"].startswith("f-")
}
problems: list[str] = []

# 1. Every text element sits inside the box it belongs to.
for e in data["elements"]:
    if e["type"] != "text":
        continue
    key = e["id"].rsplit("-", 1)[0]
    box = rects.get(key)
    if not box:
        continue
    if e["x"] < box["x"] or e["x"] + e["width"] > box["x"] + box["width"] + 1:
        problems.append(f"{e['id']}: text wider than {key}")
    if e["y"] + e["height"] > box["y"] + box["height"] - 6:
        overflow = e["y"] + e["height"] - (box["y"] + box["height"])
        problems.append(f"{e['id']}: overflows {key} bottom by {overflow:.0f}px")

# 2. Titles and short labels must not wrap.
for e in data["elements"]:
    if e["type"] == "text" and e["id"].endswith("-title"):
        if e["text"] != e["originalText"]:
            problems.append(f"{e['id']}: title wraps -> {e['text']!r}")

# 3. No two boxes overlap.
items = list(rects.values())
for i, a in enumerate(items):
    for b in items[i + 1 :]:
        if (
            a["x"] < b["x"] + b["width"]
            and b["x"] < a["x"] + a["width"]
            and a["y"] < b["y"] + b["height"]
            and b["y"] < a["y"] + a["height"]
        ):
            problems.append(f"overlap: {a['id']} and {b['id']}")

# 4. Arrows must bind to elements that exist.
for e in data["elements"]:
    if e["type"] != "arrow":
        continue
    for side in ("startBinding", "endBinding"):
        target = (e.get(side) or {}).get("elementId")
        if target and target not in els:
            problems.append(f"{e['id']}: {side} -> missing {target}")

print("\n".join(problems) if problems else f"OK: {path.name} ({len(data['elements'])} elements)")
sys.exit(1 if problems else 0)
