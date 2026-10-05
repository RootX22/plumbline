"""Command line.

Two verbs, and the split between them is the whole design: `extract` may call a
model and writes what it found; `check` calls nothing and decides. A pipeline
runs `check`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import document as doc
from . import lockfile, model, report
from .claims import Status
from .extract import from_document
from .project import scan
from .verify import verify

DEFAULT_DOCUMENTS = ["README.md", "docs", "RUNBOOK.md", "CONTRIBUTING.md"]
EXIT_OK = 0
EXIT_FAILED_CLAIMS = 1
EXIT_USAGE = 2


def _documents(targets: list[str], root: Path) -> list[Path]:
    found: list[Path] = []
    for target in targets:
        path = (root / target) if not Path(target).is_absolute() else Path(target)
        if path.is_dir():
            found.extend(sorted(p for p in path.rglob("*.md") if p.is_file()))
        elif path.is_file():
            found.append(path)
    unique: list[Path] = []
    seen = set()
    for path in found:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return unique


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _collect(path: Path, root: Path, project, locked):
    text = path.read_text(encoding="utf-8", errors="replace")
    relative = _relative(path, root)
    document = doc.read(relative, text)
    claims = list(from_document(document, project))

    entry = locked.get(relative)
    stale = False
    if entry:
        if entry.digest == lockfile.digest(text):
            known = {(c.kind, c.subject) for c in claims}
            claims.extend(c for c in entry.claims if (c.kind, c.subject) not in known)
        else:
            stale = True
    return document, claims, stale


def _check(args) -> int:
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"plumbline: {root} is not a directory", file=sys.stderr)
        return EXIT_USAGE

    project = scan(root)
    locked = lockfile.load(root / args.lock)
    targets = args.documents or DEFAULT_DOCUMENTS
    documents = _documents(targets, root)
    if not documents:
        print("plumbline: no documents to check", file=sys.stderr)
        return EXIT_USAGE

    payload = []
    failures = 0
    stale_documents = []

    for path in documents:
        document, claims, stale = _collect(path, root, project, locked)
        if stale:
            stale_documents.append(document.path)
        results = verify(claims, project, document_dir=str(Path(document.path).parent))
        failures += sum(1 for r in results if r.status is Status.FAILS)
        if args.json:
            payload.append(report.as_json(document.path, results))
        else:
            print(report.as_text(document.path, results, show_all=args.show_unchecked))

    if args.json:
        print(json.dumps({"documents": payload}, indent=2, ensure_ascii=False))
    elif stale_documents:
        print("\nrecorded claims are older than the document in: "
              + ", ".join(stale_documents) + "\nrun plumbline extract to refresh them",
              file=sys.stderr)

    return EXIT_FAILED_CLAIMS if failures else EXIT_OK


def _extract(args) -> int:
    root = Path(args.root).resolve()
    documents = _documents(args.documents or DEFAULT_DOCUMENTS, root)
    if not documents:
        print("plumbline: no documents to read", file=sys.stderr)
        return EXIT_USAGE

    client = model.Ollama(model=args.model, endpoint=args.endpoint)
    path = root / args.lock
    entries = lockfile.load(path)
    total = 0

    for document_path in documents:
        text = document_path.read_text(encoding="utf-8", errors="replace")
        relative = _relative(document_path, root)
        document = doc.read(relative, text)
        try:
            claims = model.read_prose(document, client)
        except model.ModelUnavailable as error:
            print(f"plumbline: {error}", file=sys.stderr)
            return EXIT_USAGE
        entries[relative] = lockfile.Entry(digest=lockfile.digest(text), claims=claims)
        total += len(claims)
        print(f"{relative}: {len(claims)} claims recorded")

    lockfile.save(path, entries)
    print(f"wrote {total} claims to {args.lock}")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plumbline",
        description="Check that documentation still describes the repository.")
    parser.add_argument("--version", action="version", version=_version())
    subcommands = parser.add_subparsers(dest="command")

    check = subcommands.add_parser(
        "check", help="verify recorded and fenced claims; calls no model")
    check.add_argument("documents", nargs="*", help="files or directories to check")
    check.add_argument("--root", default=".", help="repository root (default: .)")
    check.add_argument("--lock", default=str(lockfile.DEFAULT_PATH),
                       help="where recorded claims live")
    check.add_argument("--json", action="store_true", help="machine-readable output")
    check.add_argument("--show-unchecked", action="store_true",
                       help="also list claims nothing in the repository could decide")
    check.set_defaults(handler=_check)

    extract = subcommands.add_parser(
        "extract", help="read prose with a local model and record what it claims")
    extract.add_argument("documents", nargs="*")
    extract.add_argument("--root", default=".")
    extract.add_argument("--lock", default=str(lockfile.DEFAULT_PATH))
    extract.add_argument("--model", default="llama3", help="model name (default: llama3)")
    extract.add_argument("--endpoint", default="http://localhost:11434",
                         help="Ollama endpoint")
    extract.set_defaults(handler=_extract)
    return parser


def _version() -> str:
    from . import __version__
    return f"plumbline {__version__}"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "handler", None):
        parser.print_help()
        return EXIT_USAGE
    return args.handler(args)
