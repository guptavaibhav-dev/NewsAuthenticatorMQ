from __future__ import annotations

from app.schemas.envelope import InputPayload


def assert_segments_tile(payload: InputPayload) -> None:
    raw = payload.raw_text
    segs = payload.segments
    reconstructed = "".join(raw[s.start : s.end] for s in segs)
    assert reconstructed == raw
    if not segs:
        return
    assert segs[0].start == 0
    assert segs[-1].end == len(raw)
    for i, seg in enumerate(segs):
        assert seg.start < seg.end
        assert 0 <= seg.start <= len(raw)
        assert 0 <= seg.end <= len(raw)
        if i:
            assert seg.start == segs[i - 1].end
        assert not (i and segs[i - 1].end > seg.start)
