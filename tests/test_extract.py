from sahih import document, project
from sahih.claims import Kind
from sahih.extract import from_document


def claims_for(text, root):
    scanned = project.scan(root)
    return from_document(document.read("README.md", text), scanned)


def subjects(claims, kind):
    return {c.subject for c in claims if c.kind is kind}


def test_a_relative_command_is_read_as_a_script_to_run(repo):
    found = claims_for("```bash\n./scripts/deploy.sh\n```\n", repo)
    assert subjects(found, Kind.SCRIPT) == {"scripts/deploy.sh"}


def test_variables_set_in_front_of_a_command_are_read_as_claims(repo):
    found = claims_for("```bash\nDEMO_ROOT=/srv/app ./scripts/deploy.sh\n```\n", repo)
    assert subjects(found, Kind.ENV) == {"DEMO_ROOT"}


def test_ambient_variables_are_not_claims_about_the_project(repo):
    found = claims_for("```bash\nPATH=/usr/bin CI=1 ./scripts/deploy.sh\n```\n", repo)
    assert subjects(found, Kind.ENV) == set()


def test_a_line_continuation_is_folded_into_one_command(repo):
    text = "```bash\nDEMO_ROOT=/srv \\\n  ./scripts/deploy.sh\n```\n"
    found = claims_for(text, repo)
    assert subjects(found, Kind.SCRIPT) == {"scripts/deploy.sh"}


def test_commands_joined_by_operators_are_read_separately(repo):
    found = claims_for("```bash\nmake lint && make test\n```\n", repo)
    assert subjects(found, Kind.MAKE) == {"lint", "test"}


def test_an_operator_inside_quotes_does_not_split_the_command(repo):
    found = claims_for('```bash\nmake test ARGS="a && b"\n```\n', repo)
    assert subjects(found, Kind.MAKE) == {"test"}


def test_package_manager_scripts_are_recognised(repo):
    found = claims_for("```bash\nnpm run build\nyarn start\nnpm ci\n```\n", repo)
    assert subjects(found, Kind.TASK) == {"build", "start"}


def test_module_and_extra_are_recognised(repo):
    text = '```bash\npip install -e ".[dev]"\npython -m demo\n```\n'
    found = claims_for(text, repo)
    assert subjects(found, Kind.MODULE) == {"demo"}
    assert subjects(found, Kind.EXTRA) == {"dev"}


def test_compose_service_is_recognised(repo):
    found = claims_for("```bash\ndocker compose up api\n```\n", repo)
    assert subjects(found, Kind.SERVICE) == {"api"}


def test_a_block_of_output_is_not_read_as_instructions(repo):
    text = "## Example output\n\n```\nmake test\n```\n"
    assert claims_for(text, repo) == []


def test_a_prompt_prefix_is_stripped(repo):
    found = claims_for("```console\n$ make test\n```\n", repo)
    assert subjects(found, Kind.MAKE) == {"test"}


def test_absolute_paths_describe_the_machine_not_the_repository(repo):
    found = claims_for("a full `/var` is invisible to `df /`\n", repo)
    assert subjects(found, Kind.PATH) == set()


def test_a_bare_directory_name_is_not_read_as_a_repository_path(repo):
    found = claims_for("the root holds `releases/` and `shared/`\n", repo)
    assert subjects(found, Kind.PATH) == set()


def test_options_are_claimed_only_for_commands_this_repository_provides(repo):
    ours = claims_for("```bash\npython -m demo --json\n```\n", repo)
    assert subjects(ours, Kind.OPTION) == {"--json"}

    theirs = claims_for("```bash\nif myservice --check-tls; then :; fi\n```\n", repo)
    assert subjects(theirs, Kind.OPTION) == set()


def test_a_relative_link_is_claimed_and_an_external_one_is_not(repo):
    text = "[setup](docs/setup.md) and [home](https://example.com)\n"
    found = claims_for(text, repo)
    assert subjects(found, Kind.LINK) == {"docs/setup.md"}


def test_a_comment_line_is_not_a_command(repo):
    assert claims_for("```bash\n# make test\n```\n", repo) == []


def test_an_ignore_comment_silences_the_block_below_it(repo):
    text = "<!-- sahih:ignore -->\n```bash\n./nowhere.sh\n```\n"
    assert claims_for(text, repo) == []


def test_an_ignore_comment_does_not_silence_the_rest_of_the_document(repo):
    text = ("<!-- sahih:ignore -->\n```bash\n./nowhere.sh\n```\n"
            "\nand then:\n\n```bash\nmake test\n```\n")
    assert subjects(claims_for(text, repo), Kind.MAKE) == {"test"}


def test_an_ignore_comment_silences_inline_claims_on_its_own_line(repo):
    assert claims_for("see `wp-content/debug.log` <!-- sahih:ignore -->\n", repo) == []


def test_a_dotted_directory_keeps_its_dot(repo):
    (repo / ".github").mkdir()
    found = claims_for("the workflow is `.github/ci.yml`\n", repo)
    assert subjects(found, Kind.PATH) == {".github/ci.yml"}
