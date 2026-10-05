"""Turning results into something a person reads and a pipeline can act on."""

from __future__ import annotations

from collections import Counter

from .claims import Result, Status

HEADINGS = {
    "path": "file referenced", "script": "script to run", "make": "make target",
    "task": "declared script", "module": "python -m target", "extra": "install extra",
    "service": "compose service", "option": "command-line option",
    "env": "environment variable", "link": "link",
}


def summarise(results: list[Result]) -> Counter:
    return Counter(result.status.value for result in results)


def as_text(path: str, results: list[Result], show_all: bool = False) -> str:
    counts = summarise(results)
    lines = [f"{path}"]

    failures = [r for r in results if r.status is Status.FAILS]
    undecided = [r for r in results if r.status is Status.UNDECIDED]

    if not results:
        lines.append("  no checkable claims found")
        return "\n".join(lines)

    for result in sorted(failures, key=lambda r: r.claim.line):
        claim = result.claim
        label = HEADINGS.get(claim.kind.value, claim.kind.value)
        mark = "model" if claim.source.value == "model" else "doc"
        lines.append(f"  line {claim.line}: {label} {claim.subject}  [{mark}]")
        lines.append(f"    {result.detail}")
        if claim.quote:
            lines.append(f"    said: {claim.quote}")
        if result.evidence and result.evidence != claim.subject:
            lines.append(f"    nearest: {result.evidence}")

    if show_all:
        for result in sorted(undecided, key=lambda r: r.claim.line):
            claim = result.claim
            label = HEADINGS.get(claim.kind.value, claim.kind.value)
            lines.append(f"  line {claim.line}: {label} {claim.subject}  [unchecked]")
            lines.append(f"    {result.detail}")

    lines.append(
        f"  {counts.get('holds', 0)} hold, {counts.get('fails', 0)} fail, "
        f"{counts.get('undecided', 0)} unchecked")
    return "\n".join(lines)


def as_json(path: str, results: list[Result]) -> dict:
    return {
        "document": path,
        "summary": dict(summarise(results)),
        "claims": [
            {
                "kind": result.claim.kind.value,
                "subject": result.claim.subject,
                "line": result.claim.line,
                "quote": result.claim.quote,
                "source": result.claim.source.value,
                "status": result.status.value,
                "detail": result.detail,
                "evidence": result.evidence,
            }
            for result in results
        ],
    }
