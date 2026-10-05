"""Reading a Markdown file as a sequence of addressable pieces.

Only as much Markdown as the checks need: fenced blocks, inline code, links,
and the plain prose in between. A full parser would be more correct and more
than is wanted here, because every claim has to carry the line it came from so
a reader can go and look at it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

FENCE = re.compile(r"^(\s*)(`{3,}|~{3,})\s*([^\s`]*)")
INLINE_CODE = re.compile(r"`([^`\n]+)`")
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
#: Every checker needs a way to be told no. Documents quote other projects'
#: commands, show deliberately broken examples, and describe systems that are
#: not this one; without an escape hatch the only way to silence a false alarm
#: is to stop running the tool.
IGNORE = re.compile(r"<!--\s*sahih\s*:\s*ignore\s*-->")


@dataclass(frozen=True)
class Block:
    """A fenced code block, with the line its first content line sits on."""

    language: str
    lines: tuple[str, ...]
    first_line: int
    #: Nearest preceding heading, which is often what says whether the block is
    #: something to run or something to look at.
    heading: str = ""
    #: Marked with an ignore comment on the line above.
    ignored: bool = False

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@dataclass
class Document:
    path: str
    lines: list[str] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)
    #: Line number -> the prose on it, fenced blocks excluded.
    prose: dict[int, str] = field(default_factory=dict)
    #: Lines the author has asked the checker to leave alone.
    ignored_lines: set[int] = field(default_factory=set)

    def line(self, number: int) -> str:
        if 1 <= number <= len(self.lines):
            return self.lines[number - 1]
        return ""

    def quotes(self, text: str) -> list[int]:
        """Lines containing ``text`` verbatim, which is how a citation is checked."""
        needle = text.strip()
        if not needle:
            return []
        return [n for n, line in enumerate(self.lines, 1) if needle in line]


def read(path: str, text: str) -> Document:
    lines = text.splitlines()
    document = Document(path=path, lines=lines)

    fence: tuple[str, str] | None = None
    collected: list[str] = []
    started = 0
    language = ""
    heading = ""
    silence_next = False

    for number, line in enumerate(lines, 1):
        if fence is None:
            opening = FENCE.match(line)
            if opening and opening.group(2):
                fence = (opening.group(1), opening.group(2)[0] * 3)
                language = opening.group(3).lower()
                collected = []
                started = number + 1
                continue
            if IGNORE.search(line):
                document.ignored_lines.add(number)
                silence_next = True
                continue
            title = HEADING.match(line)
            if title:
                heading = title.group(2).strip()
            if line.strip():
                silence_next = False
            document.prose[number] = line
        else:
            closing = FENCE.match(line)
            if closing and closing.group(2) and closing.group(2)[0] == fence[1][0]:
                document.blocks.append(Block(language=language, lines=tuple(collected),
                                             first_line=started, heading=heading,
                                             ignored=silence_next))
                silence_next = False
                fence = None
                continue
            collected.append(line)

    if fence is not None:
        # An unterminated fence is a mistake in the document, but the content is
        # still worth reading rather than dropping on the floor.
        document.blocks.append(Block(language=language, lines=tuple(collected),
                                     first_line=started, heading=heading))
    return document


def inline_code(document: Document) -> list[tuple[int, str]]:
    """Every `backticked` span outside fenced blocks, with its line."""
    found = []
    for number, line in sorted(document.prose.items()):
        for match in INLINE_CODE.finditer(line):
            found.append((number, match.group(1).strip()))
    return found


def links(document: Document) -> list[tuple[int, str]]:
    found = []
    for number, line in sorted(document.prose.items()):
        for match in LINK.finditer(line):
            found.append((number, match.group(1).strip()))
    return found
