"""What the repository actually contains.

Gathered once and handed to every verifier. The point of collecting it up front
is that the expensive and error-prone part is not checking a claim, it is
working out where this particular project keeps things: a package may be at the
top level or under src, scripts may be loose or in a scripts directory, and
getting that wrong turns a useful report into a wall of false alarms.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "build",
             "dist", ".tox", ".mypy_cache", ".ruff_cache", ".pytest_cache",
             "vendor", ".idea", ".next", "target"}

CODE_SUFFIXES = {".py", ".sh", ".bash", ".js", ".mjs", ".cjs", ".ts", ".tsx",
                 ".jsx", ".go", ".rb", ".php", ".rs", ".java", ".yml", ".yaml",
                 ".toml", ".ini", ".cfg", ".env", ".tf", ".conf"}

MAKE_TARGET = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._/-]*)\s*:(?!=)")
MAKE_INCLUDE = re.compile(r"^(?:-|s)?include\s+(.+)$")
LONG_OPTION = re.compile(r"(?<![\w-])--[a-z][a-z0-9-]{1,}")
ENV_READ = re.compile(
    r"""(?x)
    getenv\s*\(\s*["']([A-Z][A-Z0-9_]*)["']       # C, PHP, Python
    | environ(?:\.get)?\s*[(\[]\s*["']([A-Z][A-Z0-9_]*)["']
    | process\.env\.([A-Z][A-Z0-9_]*)             # Node, attribute form
    | process\.env\[\s*["']([A-Z][A-Z0-9_]*)["']  # Node, subscript form
    | ENV\[\s*["']([A-Z][A-Z0-9_]*)["']           # Ruby
    | \$\{?([A-Z][A-Z0-9_]*)\}?                   # shell, and env files
    | ^\s*([A-Z][A-Z0-9_]*)\s*=                   # declared in an env file
    """,
    re.MULTILINE,
)


def relative_path(text: str) -> str:
    """A repository-relative path, with any leading ./ removed.

    Worth a function because the obvious spelling is wrong: lstrip and strip
    take a set of characters rather than a prefix, so strip("./") turns
    .github into github and then swears the file is missing from a repository
    that plainly has it. It cost an afternoon once; it costs a function here.
    """
    cleaned = text.strip()
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned


@dataclass
class Project:
    root: Path
    files: set[str] = field(default_factory=set)
    #: Basename -> the paths that have it, for suggesting a moved file.
    by_name: dict[str, list[str]] = field(default_factory=dict)
    make_targets: set[str] = field(default_factory=set)
    tasks: dict[str, set[str]] = field(default_factory=dict)
    python_packages: set[str] = field(default_factory=set)
    extras: set[str] = field(default_factory=set)
    services: set[str] = field(default_factory=set)
    options: set[str] = field(default_factory=set)
    env_names: set[str] = field(default_factory=set)
    #: Set when the repository has no Makefile, no package.json and so on, so a
    #: verifier can say "nothing here to check against" instead of "wrong".
    has: dict[str, bool] = field(default_factory=dict)

    def exists(self, relative: str) -> bool:
        return relative_path(relative) in self.files

    def nearest(self, name: str) -> str:
        """Where a file of this name does live, if it lives anywhere."""
        matches = self.by_name.get(Path(name).name, [])
        return matches[0] if len(matches) == 1 else ""


def _walk(root: Path) -> list[Path]:
    collected = []
    for base, directories, names in os.walk(root):
        directories[:] = [d for d in directories if d not in SKIP_DIRS
                          and not d.endswith(".egg-info")]
        for name in names:
            collected.append(Path(base) / name)
    return collected


def _read(path: Path, limit: int = 400_000) -> str:
    try:
        if path.stat().st_size > limit:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _make_targets(text: str) -> set[str]:
    targets = set()
    for line in text.splitlines():
        if line.startswith("\t") or line.lstrip().startswith("#"):
            continue
        found = MAKE_TARGET.match(line)
        if not found:
            continue
        name = found.group(1)
        if name.startswith(".") or "%" in name:
            continue
        targets.add(name)
    return targets


def _makefile_targets(path: Path, seen: set[Path]) -> set[str]:
    """Targets from a makefile and from the files it includes by literal name.

    Larger projects keep their targets in included files (kubo's GNUmakefile is
    little more than `include Rules.mk`), so reading the top file alone reports
    real targets as missing. Includes built from variables or globs need make
    itself to resolve and are left alone.
    """
    if path in seen or not path.is_file():
        return set()
    seen.add(path)
    text = _read(path)
    targets = _make_targets(text)
    for line in text.splitlines():
        found = MAKE_INCLUDE.match(line.strip())
        if not found:
            continue
        for name in found.group(1).split():
            if "$" in name or "*" in name:
                continue
            targets |= _makefile_targets(path.parent / name, seen)
    return targets


def _json_scripts(text: str) -> set[str]:
    """Script names from a package.json or composer.json.

    Parsed with the json module when the file is valid; a manifest with a
    trailing comma is common enough that a line scan is kept as a fallback
    rather than losing the whole file to one typo.
    """
    import json

    try:
        data = json.loads(text)
    except ValueError:
        inside = False
        found = set()
        for line in text.splitlines():
            stripped = line.strip()
            if re.match(r'"scripts"\s*:\s*\{', stripped):
                inside = True
                continue
            if inside:
                if stripped.startswith("}"):
                    break
                name = re.match(r'"([^"]+)"\s*:', stripped)
                if name:
                    found.add(name.group(1))
        return found
    scripts = data.get("scripts")
    if isinstance(scripts, dict):
        return set(scripts)
    return set()


def _compose_services(text: str) -> set[str]:
    """Top-level service names, read by indentation.

    A compose file is YAML and this is not a YAML parser. It handles the shape
    every compose file in practice has, and will miss anchors and merge keys;
    that limit is documented rather than papered over.
    """
    services: set[str] = set()
    inside = False
    indent = None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if re.match(r"^services\s*:\s*$", line):
            inside = True
            continue
        if not inside:
            continue
        current = len(line) - len(line.lstrip())
        if current == 0:
            break
        if indent is None:
            indent = current
        if current == indent:
            name = re.match(r"^\s*([A-Za-z0-9._-]+)\s*:", line)
            if name:
                services.add(name.group(1))
    return services


def scan(root: Path) -> Project:
    project = Project(root=root)
    paths = _walk(root)

    for path in paths:
        relative = path.relative_to(root).as_posix()
        project.files.add(relative)
        project.by_name.setdefault(path.name, []).append(relative)

    included: set[Path] = set()
    for path in paths:
        relative = path.relative_to(root).as_posix()
        name = path.name

        if name in {"Makefile", "makefile", "GNUmakefile"}:
            project.make_targets |= _makefile_targets(path, included)
        elif name in {"package.json", "composer.json"}:
            project.tasks.setdefault(name, set()).update(_json_scripts(_read(path)))
        elif name == "pyproject.toml":
            try:
                data = tomllib.loads(_read(path))
            except (tomllib.TOMLDecodeError, ValueError):
                data = {}
            optional = data.get("project", {}).get("optional-dependencies", {})
            if isinstance(optional, dict):
                project.extras |= set(optional)
        elif re.fullmatch(r"(docker-)?compose(\.[\w-]+)?\.ya?ml", name):
            project.services |= _compose_services(_read(path))

        if path.suffix == ".py" and name == "__init__.py":
            package = path.parent
            if package.name not in SKIP_DIRS:
                project.python_packages.add(package.name)

        if path.suffix in CODE_SUFFIXES:
            text = _read(path)
            if not text:
                continue
            if path.suffix in {".py", ".sh", ".bash", ".js", ".mjs", ".ts", ".go",
                               ".rb", ".php", ".rs"}:
                project.options |= set(LONG_OPTION.findall(text))
            for groups in ENV_READ.findall(text):
                for value in groups:
                    if value:
                        project.env_names.add(value)

    project.has = {
        "make": bool(project.make_targets) or any(
            n in project.files for n in ("Makefile", "makefile", "GNUmakefile")),
        "node": "package.json" in project.files,
        "composer": "composer.json" in project.files,
        "python": "pyproject.toml" in project.files or bool(project.python_packages),
        "compose": any(re.fullmatch(r"(docker-)?compose(\.[\w-]+)?\.ya?ml", Path(f).name)
                       for f in project.files),
    }
    return project
