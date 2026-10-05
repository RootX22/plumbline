"""What a document asserts about the repository it describes.

A claim is deliberately small: a kind, the thing it names, and the line it was
read from. Everything else is the verifier's business. Keeping claims narrow is
what lets the same type carry something read out of a code fence and something
a language model noticed in a sentence, and be checked by the same code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Kind(StrEnum):
    #: A file or directory the reader is told exists.
    PATH = "path"
    #: A script the reader is told to execute, named the way they would type it.
    SCRIPT = "script"
    #: A make target.
    MAKE = "make"
    #: A script declared in package.json, composer.json, or similar.
    TASK = "task"
    #: A Python module meant to be runnable with -m.
    MODULE = "module"
    #: An optional-dependency group, as in pip install -e ".[dev]".
    EXTRA = "extra"
    #: A service named in a compose file.
    SERVICE = "service"
    #: A command-line option this project's own tooling is said to accept.
    OPTION = "option"
    #: An environment variable the software is said to read.
    ENV = "env"
    #: A link pointing inside the repository.
    LINK = "link"


#: Who produced the claim. Kept on the claim because the two deserve different
#: treatment: a fence is unambiguous, a sentence is an interpretation.
class Source(StrEnum):
    DOCUMENT = "document"
    MODEL = "model"


@dataclass(frozen=True)
class Claim:
    kind: Kind
    #: The thing named: a path, a target, a flag, a variable.
    subject: str
    line: int
    #: The text the claim was read from, verbatim, so a reader can find it.
    quote: str
    source: Source = Source.DOCUMENT
    #: Free-form detail a verifier may need, such as the file a target belongs to.
    context: dict = field(default_factory=dict)

    def key(self) -> tuple:
        return (self.kind.value, self.subject, self.line)


class Status(StrEnum):
    HOLDS = "holds"
    FAILS = "fails"
    #: Checked, but the repository does not contain enough to decide. Reported
    #: rather than silently passed, because a check that quietly gives up is
    #: worse than one that admits it.
    UNDECIDED = "undecided"


@dataclass(frozen=True)
class Result:
    claim: Claim
    status: Status
    #: One sentence. What was looked for, and what was there instead.
    detail: str
    #: Where to look: a path, a target name, the closest thing that does exist.
    evidence: str = ""

    @property
    def failed(self) -> bool:
        return self.status is Status.FAILS
