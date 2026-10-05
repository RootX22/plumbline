from plumbline import project
from plumbline.claims import Claim, Kind, Status
from plumbline.verify import verify


def check(claim, root):
    return verify([claim], project.scan(root))[0]


def claim(kind, subject, **context):
    return Claim(kind=kind, subject=subject, line=1, quote=subject, context=context)


def test_a_script_that_moved_is_reported_with_where_it_went(repo):
    result = check(claim(Kind.SCRIPT, "deploy.sh", spelled="./deploy.sh"), repo)
    assert result.status is Status.FAILS
    assert result.evidence == "scripts/deploy.sh"
    assert "will not run" in result.detail


def test_a_script_at_the_path_given_holds(repo):
    assert check(claim(Kind.SCRIPT, "scripts/deploy.sh"), repo).status is Status.HOLDS


def test_a_make_target_is_checked_against_the_makefile(repo):
    assert check(claim(Kind.MAKE, "test"), repo).status is Status.HOLDS
    missing = check(claim(Kind.MAKE, "tset"), repo)
    assert missing.status is Status.FAILS
    assert missing.evidence == "test"


def test_a_make_target_without_a_makefile_is_left_undecided(tmp_path):
    assert check(claim(Kind.MAKE, "test"), tmp_path).status is Status.UNDECIDED


def test_declared_scripts_are_checked_against_the_manifest(repo):
    def task(name):
        return check(claim(Kind.TASK, name, manifest="package.json"), repo).status

    assert task("build") is Status.HOLDS
    assert task("nope") is Status.FAILS


def test_a_module_needs_a_main_to_be_runnable(repo):
    assert check(claim(Kind.MODULE, "demo"), repo).status is Status.HOLDS
    (repo / "demo/__main__.py").unlink()
    broken = check(claim(Kind.MODULE, "demo"), repo)
    assert broken.status is Status.FAILS
    assert "__main__" in broken.detail


def test_a_src_layout_package_is_found_too(tmp_path):
    (tmp_path / "src/demo").mkdir(parents=True)
    (tmp_path / "src/demo/__init__.py").write_text("")
    (tmp_path / "src/demo/__main__.py").write_text("")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    assert check(claim(Kind.MODULE, "demo"), tmp_path).status is Status.HOLDS


def test_an_install_extra_is_checked_against_pyproject(repo):
    assert check(claim(Kind.EXTRA, "dev"), repo).status is Status.HOLDS
    assert check(claim(Kind.EXTRA, "docs"), repo).status is Status.FAILS


def test_a_compose_service_is_checked(repo):
    assert check(claim(Kind.SERVICE, "api"), repo).status is Status.HOLDS
    assert check(claim(Kind.SERVICE, "db"), repo).status is Status.FAILS


def test_an_option_must_appear_in_the_source(repo):
    assert check(claim(Kind.OPTION, "--json"), repo).status is Status.HOLDS
    assert check(claim(Kind.OPTION, "--jsonl"), repo).status is Status.FAILS


def test_an_environment_variable_nothing_reads_is_reported(repo):
    assert check(claim(Kind.ENV, "DEMO_ROOT"), repo).status is Status.HOLDS
    dead = check(claim(Kind.ENV, "DEMO_OLD"), repo)
    assert dead.status is Status.FAILS
    assert "dead" in dead.detail


def test_a_bare_filename_that_resolves_once_is_an_answer(repo):
    result = check(claim(Kind.PATH, "deploy.sh"), repo)
    assert result.status is Status.HOLDS
    assert result.evidence == "scripts/deploy.sh"


def test_a_path_under_a_directory_this_repository_lacks_is_undecided(repo):
    result = check(claim(Kind.PATH, "wp-content/debug.log"), repo)
    assert result.status is Status.UNDECIDED
    assert "another system" in result.detail


def test_a_path_under_a_directory_this_repository_has_is_a_failure(repo):
    result = check(claim(Kind.PATH, "docs/missing.md"), repo)
    assert result.status is Status.FAILS


def test_a_broken_relative_link_fails(repo):
    results = verify([claim(Kind.LINK, "docs/gone.md")], project.scan(repo))
    assert results[0].status is Status.FAILS


def test_a_link_resolves_relative_to_the_document(repo):
    scanned = project.scan(repo)
    results = verify([claim(Kind.LINK, "setup.md")], scanned, document_dir="docs")
    assert results[0].status is Status.HOLDS


def test_a_dotfile_path_is_not_mistaken_for_a_missing_one(repo):
    """strip("./") removes the dot of .github and then calls the file missing."""
    (repo / ".github").mkdir()
    (repo / ".github/ci.yml").write_text("name: ci\n")
    assert check(claim(Kind.PATH, ".github/ci.yml"), repo).status is Status.HOLDS
    assert check(claim(Kind.PATH, "./.github/ci.yml"), repo).status is Status.HOLDS
