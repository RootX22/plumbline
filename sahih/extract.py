"""Reading claims out of a document, without a language model.

Everything here is a shape that can be recognised with certainty: a command in
a fenced block, a path in backticks, a relative link. Sentences are left alone;
they are the model's job, and the model's output comes back through the same
Claim type so both are checked by the same code.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

from .claims import Claim, Kind, Source
from .document import Document, inline_code, links
from .project import relative_path

SHELL_LANGUAGES = {"", "bash", "sh", "shell", "zsh", "console", "shell-session",
                   "terminal", "command"}

#: Blocks under these headings are showing you what came out, not what to run.
OUTPUT_HEADINGS = re.compile(r"\b(output|example output|result|sample|report|"
                             r"what you (get|see)|prints?)\b", re.I)

PROMPT = re.compile(r"^\s*(?:\$|>)\s+")
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
OPERATOR = re.compile(r"\s*(?:&&|\|\||\||;)\s*")

#: Variables the environment provides, or a third-party library reads. Naming
#: one in a README is not a claim about this repository's own code.
AMBIENT_ENV = {
    "PATH", "HOME", "USER", "SHELL", "PWD", "LANG", "LC_ALL", "TERM", "TMPDIR",
    "EDITOR", "PAGER", "HOSTNAME", "DISPLAY", "TZ", "CI", "GITHUB_TOKEN",
    "GITHUB_ACTIONS", "GITHUB_WORKSPACE", "GITHUB_REPOSITORY", "RUNNER_OS",
    "PYTHONPATH", "PYTHONUNBUFFERED", "VIRTUAL_ENV", "NODE_ENV", "NO_COLOR",
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION", "AWS_PROFILE",
    "DOCKER_HOST", "KUBECONFIG", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
}

PATH_LIKE = re.compile(r"^[\w./@-]+$")
KNOWN_SUFFIXES = {".py", ".sh", ".md", ".toml", ".yml", ".yaml", ".json", ".cfg",
                  ".ini", ".txt", ".lock", ".env", ".service", ".conf", ".tf",
                  ".js", ".ts", ".go", ".rb", ".php", ".sql", ".Dockerfile"}

ENV_NAME = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$")

#: Subcommands of the package managers that are not script names.
COMPOSE_VERBS = {"up", "run", "exec", "logs", "restart", "stop"}

NPM_BUILTINS = {"install", "i", "ci", "run", "run-script", "publish",
                "init", "exec", "update", "audit", "link", "pack", "add", "remove",
                "dlx", "create", "why", "outdated", "login", "version"}


def _join_continuations(lines: tuple[str, ...]) -> list[tuple[int, str]]:
    """Fold backslash continuations, keeping the line the command started on."""
    joined: list[tuple[int, str]] = []
    buffer = ""
    start = 0
    for offset, raw in enumerate(lines):
        line = raw.rstrip()
        if not buffer:
            start = offset
        if line.endswith("\\"):
            buffer += line[:-1] + " "
            continue
        buffer += line
        joined.append((start, buffer))
        buffer = ""
    if buffer:
        joined.append((start, buffer))
    return joined


def _commands(text: str) -> list[str]:
    """Split one shell line into the commands it actually runs."""
    pieces = []
    depth = 0
    quote = ""
    current = ""
    index = 0
    while index < len(text):
        char = text[index]
        if quote:
            current += char
            if char == quote:
                quote = ""
            index += 1
            continue
        if char in "\"'":
            quote = char
            current += char
            index += 1
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        if depth == 0:
            operator = OPERATOR.match(text, index)
            if operator and operator.group(0).strip():
                pieces.append(current)
                current = ""
                index = operator.end()
                continue
        current += char
        index += 1
    pieces.append(current)
    return [piece.strip() for piece in pieces if piece.strip()]


def _tokens(command: str) -> tuple[list[str], list[str]]:
    """The command's words, and the variables set in front of it."""
    try:
        parsed = shlex.split(command, comments=True)
    except ValueError:
        return [], []
    assigned = []
    while parsed and ASSIGNMENT.match(parsed[0]):
        assigned.append(parsed[0].split("=", 1)[0])
        parsed = parsed[1:]
    return parsed, assigned


def _is_output_block(block) -> bool:
    if block.language in {"text", "txt", "json", "yaml", "yml", "diff", "log"}:
        return True
    if OUTPUT_HEADINGS.search(block.heading or ""):
        return True
    return block.language not in SHELL_LANGUAGES


def _options(tokens: list[str]) -> list[str]:
    return [t for t in tokens if t.startswith("--") and len(t) > 2 and "=" not in t]


def _owns(program: str, project) -> bool:
    """Whether a command names something this repository provides.

    Without this the checker reports every flag in every illustrative snippet.
    A README that shows `if myservice --check-tls` is talking about somebody
    else's program, and has claimed nothing about this one.
    """
    if program.startswith("./") or "/" in program:
        return project.exists(program)
    base = Path(program).name
    if base in project.python_packages:
        return True
    return any(Path(f).name == base for f in project.files)


def from_document(document: Document, project) -> list[Claim]:
    claims: list[Claim] = []

    def add(kind: Kind, subject: str, line: int, quote: str, **context) -> None:
        if not subject:
            return
        claims.append(Claim(kind=kind, subject=subject, line=line,
                            quote=quote.strip()[:200], source=Source.DOCUMENT,
                            context=context))

    for block in document.blocks:
        if block.ignored or _is_output_block(block):
            continue
        for offset, raw in _join_continuations(block.lines):
            line_number = block.first_line + offset
            stripped = PROMPT.sub("", raw).strip()
            if not stripped or stripped.startswith("#"):
                continue
            for command in _commands(stripped):
                tokens, assigned = _tokens(command)
                if not tokens:
                    continue
                claims.extend(_from_command(tokens, line_number, raw, project))
                for name in assigned:
                    if ENV_NAME.match(name) and name not in AMBIENT_ENV:
                        add(Kind.ENV, name, line_number, raw)

    for line_number, span in inline_code(document):
        if line_number in document.ignored_lines:
            continue
        text = span.strip()
        if not PATH_LIKE.match(text) or text.startswith("-"):
            continue
        if text.startswith("/"):
            # An absolute path is a statement about the machine the software
            # runs on. The repository has nothing to say about it.
            continue
        if text.startswith(("http:", "https:", "git@")) or text.endswith("/*"):
            continue
        inner = text.strip("/")
        if "/" in inner or Path(text).suffix in KNOWN_SUFFIXES:
            add(Kind.PATH, inner, line_number, text)

    for line_number, target in links(document):
        if line_number in document.ignored_lines:
            continue
        if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
            continue
        add(Kind.LINK, target.split("#", 1)[0], line_number, target)

    return _dedupe(claims)


def _from_command(tokens: list[str], line: int, quote: str, project) -> list[Claim]:
    program, arguments = tokens[0], tokens[1:]
    found: list[Claim] = []

    def claim(kind: Kind, subject: str, **context) -> None:
        found.append(Claim(kind=kind, subject=subject, line=line,
                           quote=quote.strip()[:200], source=Source.DOCUMENT,
                           context=context))

    base = Path(program).name

    if program.startswith("./") or (program.startswith("../")):
        claim(Kind.SCRIPT, relative_path(program), spelled=program)
    elif base == "make":
        for argument in arguments:
            if argument.startswith("-") or "=" in argument:
                continue
            claim(Kind.MAKE, argument)
    elif base in {"npm", "pnpm", "yarn", "bun"}:
        if arguments and arguments[0] in {"run", "run-script"} and len(arguments) > 1:
            claim(Kind.TASK, arguments[1], manifest="package.json")
        elif (arguments and arguments[0] not in NPM_BUILTINS
              and not arguments[0].startswith("-")):
            claim(Kind.TASK, arguments[0], manifest="package.json")
    elif base == "composer":
        if arguments and arguments[0] in {"run", "run-script"} and len(arguments) > 1:
            claim(Kind.TASK, arguments[1], manifest="composer.json")
    elif base in {"python", "python3", "py"}:
        if arguments and arguments[0] == "-m" and len(arguments) > 1:
            claim(Kind.MODULE, arguments[1])
        elif arguments and arguments[0].endswith(".py"):
            claim(Kind.PATH, arguments[0])
    elif base in {"pip", "pip3"} or (base in {"python", "python3"} and "pip" in arguments):
        for argument in arguments:
            extra = re.fullmatch(r'["\']?\.\[([a-zA-Z0-9_,-]+)\]["\']?', argument)
            if extra:
                for name in extra.group(1).split(","):
                    claim(Kind.EXTRA, name.strip())
    elif base == "docker-compose" or (base == "docker" and arguments[:1] == ["compose"]):
        rest = arguments[1:] if base == "docker" else arguments
        if rest and rest[0] in COMPOSE_VERBS:
            for argument in rest[1:]:
                if not argument.startswith("-"):
                    claim(Kind.SERVICE, argument)
                    break

    owner, shown = program, program
    runs_module = (base in {"python", "python3", "py"}
                   and arguments[:1] == ["-m"] and len(arguments) > 1)
    if runs_module:
        owner, shown = arguments[1], f"python -m {arguments[1]}"
    if _owns(owner, project):
        for option in _options(arguments):
            claim(Kind.OPTION, option, program=shown)

    return found


def _dedupe(claims: list[Claim]) -> list[Claim]:
    seen = set()
    unique = []
    for claim in claims:
        key = (claim.kind, claim.subject)
        if key in seen:
            continue
        seen.add(key)
        unique.append(claim)
    return unique
