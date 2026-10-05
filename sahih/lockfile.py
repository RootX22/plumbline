"""Remembering what the model found, so checking never needs to call it.

Documentation changes rarely; a model is slow, and on some runners absent. The
claims a model found are written here once and verified from then on, which
keeps a pipeline's verdict a function of the repository alone. Each entry is
tied to the digest of the document it came from, so a document edited after its
claims were recorded is reported as stale instead of checked against notes that
no longer describe it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .claims import Claim, Kind, Source

VERSION = 1
DEFAULT_PATH = Path(".sahih/claims.json")


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@dataclass
class Entry:
    digest: str
    claims: list[Claim]


def load(path: Path) -> dict[str, Entry]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if data.get("version") != VERSION:
        return {}
    entries: dict[str, Entry] = {}
    for document, record in (data.get("documents") or {}).items():
        claims = []
        for item in record.get("claims", []):
            try:
                kind = Kind(item["kind"])
            except (KeyError, ValueError):
                continue
            claims.append(Claim(kind=kind, subject=item.get("subject", ""),
                                line=int(item.get("line", 0)),
                                quote=item.get("quote", ""), source=Source.MODEL))
        entries[document] = Entry(digest=record.get("digest", ""), claims=claims)
    return entries


def save(path: Path, entries: dict[str, Entry]) -> None:
    payload = {
        "version": VERSION,
        "documents": {
            document: {
                "digest": entry.digest,
                "claims": [
                    {"kind": c.kind.value, "subject": c.subject,
                     "line": c.line, "quote": c.quote}
                    for c in entry.claims
                ],
            }
            for document, entry in sorted(entries.items())
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
