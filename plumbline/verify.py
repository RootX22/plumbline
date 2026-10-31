"""Deciding whether a claim still holds.

One function per kind, all of them deterministic and all of them allowed to
answer "undecided". That third answer is the difference between a checker
people keep and one they uninstall: if a repository has no Makefile, a claim
about a make target has not been disproved, it has merely gone unchecked, and
saying so costs nothing while guessing costs trust.
"""

from __future__ import annotations

import difflib
import posixpath
import sys
from urllib.parse import unquote

from .claims import Claim, Kind, Result, Status
from .project import Project, relative_path


def _closest(name: str, pool) -> str:
    matches = difflib.get_close_matches(name, sorted(pool), n=1, cutoff=0.72)
    return matches[0] if matches else ""


#: Not in the standard library, but present wherever Python is installed the usual
#: way, and documentation leans on it for every install command.
BUNDLED_MODULES = {"pip"}


def _holds(claim: Claim, detail: str, evidence: str = "") -> Result:
    return Result(claim=claim, status=Status.HOLDS, detail=detail, evidence=evidence)


def _fails(claim: Claim, detail: str, evidence: str = "") -> Result:
    return Result(claim=claim, status=Status.FAILS, detail=detail, evidence=evidence)


def _undecided(claim: Claim, detail: str) -> Result:
    return Result(claim=claim, status=Status.UNDECIDED, detail=detail)


def _path(claim: Claim, project: Project) -> Result:
    target = relative_path(claim.subject)
    if project.exists(target):
        return _holds(claim, "the path exists", target)
    if (project.root / target).is_dir():
        return _holds(claim, "the directory exists", target)

    elsewhere = project.nearest(target)
    if "/" not in target.strip("/") and elsewhere:
        # A bare filename in prose points at a file rather than at a location.
        # One file of that name in the repository is an answer, not an error;
        # a command written as ./name is a different claim and _script has it.
        return _holds(claim, f"the file is at {elsewhere}", elsewhere)
    if elsewhere and elsewhere != target:
        return _fails(claim, f"no {target} in the repository; a file of that name is at "
                             f"{elsewhere}", elsewhere)

    # Nothing of that name is here at all. Documentation routinely describes
    # paths on a deployment target, or inside the software being inspected, and
    # from the text alone those are indistinguishable from a path that was
    # meant to be in this repository. The one tell worth trusting is the
    # leading directory: if the repository has it, the path was addressed here.
    head = target.split("/", 1)[0] if "/" in target.strip("/") else ""
    if head and not _has_directory(project, head):
        return _undecided(claim, f"no {head} directory here, so {target} appears to describe "
                                 f"another system rather than this repository")
    if not head:
        return _undecided(claim, f"nothing named {target} in the repository, and the name "
                                 f"carries no path saying where it should be")
    return _fails(claim, f"no {target} in the repository, though {head}/ exists",
                  _closest(target, project.files))


def _has_directory(project: Project, name: str) -> bool:
    if (project.root / name).is_dir():
        return True
    prefix = name.rstrip("/") + "/"
    return any(f.startswith(prefix) for f in project.files)


def _script(claim: Claim, project: Project) -> Result:
    spelled = claim.context.get("spelled", "./" + claim.subject)
    claim_subject = relative_path(claim.subject)
    target = claim_subject
    if project.exists(target):
        return _holds(claim, f"{spelled} resolves to {target}", target)
    elsewhere = project.nearest(target)
    if elsewhere:
        return _fails(claim, f"{spelled} will not run from the repository root; the script "
                             f"is at {elsewhere}", elsewhere)
    built_from = project.built_binaries.get(target)
    if built_from:
        return _undecided(claim, f"{spelled} is the program built from {built_from}, not a "
                                 f"file kept in the repository")
    return _fails(claim, f"no executable {target} in the repository",
                  _closest(target, project.files))


def _make(claim: Claim, project: Project) -> Result:
    if not project.has.get("make"):
        return _undecided(claim, "no Makefile in the repository to check the target against")
    if claim.subject in project.make_targets:
        return _holds(claim, "the target is defined", claim.subject)
    return _fails(claim, f"the Makefile defines no target {claim.subject}",
                  _closest(claim.subject, project.make_targets))


def _task(claim: Claim, project: Project) -> Result:
    manifest = claim.context.get("manifest", "package.json")
    declared = project.tasks.get(manifest, set())
    if manifest not in project.files:
        return _undecided(claim, f"no {manifest} in the repository to check the script against")
    if claim.subject in declared:
        return _holds(claim, f"{manifest} declares the script", claim.subject)
    return _fails(claim, f"{manifest} declares no script {claim.subject}",
                  _closest(claim.subject, declared))


def _module(claim: Claim, project: Project) -> Result:
    name = claim.subject.split(".", 1)[0]
    if name in sys.stdlib_module_names or name in BUNDLED_MODULES:
        return _holds(claim, f"{name} ships with Python", name)
    if not project.has.get("python"):
        return _undecided(claim,
                          "no Python package here to check the module against")
    for prefix in ("", "src/"):
        package = f"{prefix}{name}"
        if f"{package}/__init__.py" in project.files:
            if f"{package}/__main__.py" in project.files:
                return _holds(claim, f"{package} is runnable with -m", package)
            return _fails(claim, f"{package} has no __main__.py, so python -m {name} will "
                                 f"not start it", package)
    # A name close to one of this repository's packages is a typo or a rename.
    # Anything else is a tool installed alongside, such as pytest or uvicorn,
    # which the repository has no way to vouch for.
    closest = _closest(name, project.python_packages)
    if closest:
        return _fails(claim, f"no importable package named {name}", closest)
    return _undecided(claim, f"{name} is not a package in this repository; it is "
                             f"presumably installed separately")


def _extra(claim: Claim, project: Project) -> Result:
    if "pyproject.toml" not in project.files:
        return _undecided(claim, "no pyproject.toml to check the extra against")
    if claim.subject in project.extras:
        return _holds(claim, "the optional-dependency group is declared", claim.subject)
    return _fails(claim, f"pyproject.toml declares no optional-dependency group "
                         f"{claim.subject}", _closest(claim.subject, project.extras))


def _service(claim: Claim, project: Project) -> Result:
    if not project.has.get("compose"):
        return _undecided(claim, "no compose file to check the service against")
    if claim.subject in project.services:
        return _holds(claim, "the compose file defines the service", claim.subject)
    return _fails(claim, f"no service {claim.subject} in the compose file",
                  _closest(claim.subject, project.services))


def _option(claim: Claim, project: Project) -> Result:
    if not project.options:
        return _undecided(claim, "no source in the repository defines any long option")
    if claim.subject in project.options:
        return _holds(claim, "the option appears in the source", claim.subject)
    program = claim.context.get("program", "the command")
    return _fails(claim, f"nothing in the repository defines {claim.subject}, which "
                         f"{program} is shown accepting",
                  _closest(claim.subject, project.options))


def _env(claim: Claim, project: Project) -> Result:
    if not project.env_names:
        return _undecided(claim, "nothing in the repository reads the environment")
    if claim.subject in project.env_names:
        return _holds(claim, "the variable is read by the code", claim.subject)
    return _fails(claim, f"nothing reads {claim.subject}; it is documented but dead",
                  _closest(claim.subject, project.env_names))


def _link(claim: Claim, project: Project, document_dir: str = "") -> Result:
    # Markdown percent-encodes a space or a non-ASCII name; the file on disk is
    # spelled plainly, so the link is compared in that spelling.
    target = unquote(claim.subject.strip())
    if not target:
        return _undecided(claim, "the link has no target")
    if target.startswith("/"):
        # GitHub resolves a leading slash against the repository root.
        candidates = [target.lstrip("/")]
    else:
        candidates = [target]
        if document_dir:
            candidates.insert(0, f"{document_dir}/{target}")
    for candidate in candidates:
        normalised = relative_path(posixpath.normpath(candidate))
        if normalised in project.files or (project.root / normalised).is_dir():
            return _holds(claim, "the link target exists", normalised)
    elsewhere = project.nearest(target)
    if elsewhere:
        return _fails(claim, f"the link points at {target}, which is at {elsewhere}", elsewhere)
    return _fails(claim, f"the link points at {target}, which is not in the repository",
                  _closest(target, project.files))


_VERIFIERS = {
    Kind.PATH: _path,
    Kind.SCRIPT: _script,
    Kind.MAKE: _make,
    Kind.TASK: _task,
    Kind.MODULE: _module,
    Kind.EXTRA: _extra,
    Kind.SERVICE: _service,
    Kind.OPTION: _option,
    Kind.ENV: _env,
}


def verify(claims, project: Project, document_dir: str = "") -> list[Result]:
    results = []
    for claim in claims:
        if claim.kind is Kind.LINK:
            results.append(_link(claim, project, document_dir))
            continue
        verifier = _VERIFIERS.get(claim.kind)
        if verifier is None:
            results.append(_undecided(claim, "no verifier for this kind of claim"))
            continue
        results.append(verifier(claim, project))
    return results
