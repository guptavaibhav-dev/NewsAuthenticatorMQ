"""Media verification hook (C2PA, reverse image). Not used in v1."""

from app.schemas.envelope import ToolResult


async def inspect_media(_payload) -> ToolResult:
    return ToolResult(
        tool="media",
        status="skipped",
        detail="Visual/provenance tools are reserved for a later thesis iteration.",
    )
