"""Letting a language model read the prose, and not letting it decide anything.

A fenced command is unambiguous and the extractor in extract.py finds it. The
claims that get people hurt are the ones written as English: "the service
listens on 8080", "credentials live in config/secrets.yml", "run the migration
before starting the worker". Finding those in free text is what a model is
genuinely better at than a regular expression.

What the model is not allowed to do is say whether a claim is true. It returns
candidates; verify.py decides. Two consequences follow, and both matter more
than they look:

* a hallucinated claim cannot pass. It is checked against the repository like
  any other, and a claim about a file that was never mentioned simply fails to
  cite the document and is dropped before it reaches a verifier.
* the verdict does not move when the model does. Re-running with a different
  model, or a different temperature, can change which claims are found. It
  cannot change the answer for a claim already found, because that answer comes
  from the filesystem.

The second point is why `sahih extract` writes a lockfile and `sahih check`
reads it. Continuous integration verifies a fixed set of claims and never calls
a model; refreshing the set is a deliberate act with a diff to review.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from .claims import Claim, Kind, Source
from .document import Document

PROMPT = """You are reading project documentation to find statements that can be
checked against the repository it describes.

Return a JSON array. Each element describes one checkable statement:

  kind    one of: path, script, make, task, module, extra, service, option, env
  subject the exact thing named - a file path, a target name, a flag, a variable
  line    the line number the statement appears on
  quote   the text from that line, copied exactly, that makes the statement

Rules:
- Only statements about THIS project. Ignore examples about other software.
- Only what is asserted to exist. Ignore plans, suggestions and what-ifs.
- Copy the quote character for character from the line you cite. Do not tidy it.
- If a line carries no checkable statement, skip it. An empty array is a fine answer.
- Return the array and nothing else. No prose, no code fence.

Lines:
{lines}
"""

JSON_ARRAY = re.compile(r"\[.*\]", re.S)


class ModelUnavailable(RuntimeError):
    """The model could not be reached. Callers fall back to the fenced claims."""


@dataclass
class Ollama:
    """A local model over Ollama's HTTP API.

    Local by default because documentation is not always public, and sending a
    private repository's internals to a third party to lint a README is a poor
    trade. Nothing here depends on Ollama specifically; anything with a
    ``generate`` method returning text will do.
    """

    model: str = "llama3"
    endpoint: str = "http://localhost:11434"
    timeout: float = 120.0

    def generate(self, prompt: str) -> str:
        payload = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            # Nothing here benefits from invention.
            "options": {"temperature": 0.0},
        }).encode()
        request = urllib.request.Request(
            f"{self.endpoint.rstrip('/')}/api/generate",
            data=payload, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8", "replace"))
        except (urllib.error.URLError, OSError) as error:
            raise ModelUnavailable(f"{self.endpoint} did not answer: {error}") from error
        except ValueError as error:
            raise ModelUnavailable(
                f"{self.endpoint} returned something that is not JSON") from error
        return str(body.get("response", ""))


def numbered_prose(document: Document, limit: int = 400) -> str:
    """The document's prose with line numbers, fenced blocks left out."""
    rows = []
    for number, text in sorted(document.prose.items()):
        if not text.strip():
            continue
        rows.append(f"{number}: {text}")
        if len(rows) >= limit:
            break
    return "\n".join(rows)


def _parse(raw: str) -> list[dict]:
    found = JSON_ARRAY.search(raw or "")
    if not found:
        return []
    try:
        data = json.loads(found.group(0))
    except ValueError:
        return []
    return [item for item in data if isinstance(item, dict)]


def admit(candidates: list[dict], document: Document) -> list[Claim]:
    """Keep the candidates the document actually supports.

    A candidate survives only if its quote appears in the document word for
    word and its subject appears inside that quote. Both conditions are cheap
    and neither can be satisfied by inventing something.
    """
    admitted: list[Claim] = []
    for item in candidates:
        kind_name = str(item.get("kind", "")).strip().lower()
        try:
            kind = Kind(kind_name)
        except ValueError:
            continue

        subject = str(item.get("subject", "")).strip().strip("`'\" ")
        quote = str(item.get("quote", "")).strip()
        if not subject or not quote:
            continue

        try:
            stated = int(item.get("line", 0))
        except (TypeError, ValueError):
            continue

        if quote not in document.line(stated):
            # Allow the model to be off by a line or two, but make it prove
            # the quote exists somewhere; one found nowhere is an invention.
            elsewhere = document.quotes(quote)
            if not elsewhere:
                continue
            stated = min(elsewhere, key=lambda n: abs(n - stated))

        if subject not in quote:
            continue
        if stated not in document.prose:
            # Fenced content is already read exactly by extract.py. Confining
            # the model to prose keeps the two from disagreeing about the same
            # line and makes the division of labour checkable.
            continue

        admitted.append(Claim(kind=kind, subject=subject, line=stated,
                              quote=quote[:200], source=Source.MODEL))
    return admitted


def read_prose(document: Document, client) -> list[Claim]:
    lines = numbered_prose(document)
    if not lines.strip():
        return []
    return admit(_parse(client.generate(PROMPT.format(lines=lines))), document)
