from plumbline import project


def test_make_targets_ignore_recipes_variables_and_patterns(tmp_path):
    (tmp_path / "Makefile").write_text(
        "CC := gcc\n"
        ".PHONY: test\n"
        "test:\n"
        "\techo not-a-target:\n"
        "%.o: %.c\n"
        "\t$(CC) -c $<\n"
        "lint:\n"
        "\truff check .\n")
    scanned = project.scan(tmp_path)
    assert scanned.make_targets == {"test", "lint"}


def test_a_manifest_with_a_trailing_comma_still_yields_its_scripts(tmp_path):
    (tmp_path / "package.json").write_text(
        '{\n  "scripts": {\n    "build": "tsc",\n    "start": "node .",\n  }\n}')
    scanned = project.scan(tmp_path)
    assert scanned.tasks["package.json"] == {"build", "start"}


def test_compose_services_are_read_from_the_top_level_only(tmp_path):
    (tmp_path / "compose.yml").write_text(
        "version: '3'\n"
        "services:\n"
        "  api:\n"
        "    image: demo\n"
        "    environment:\n"
        "      nested: not-a-service\n"
        "  worker:\n"
        "    image: demo\n"
        "volumes:\n"
        "  data:\n")
    scanned = project.scan(tmp_path)
    assert scanned.services == {"api", "worker"}


def test_vendor_directories_are_not_walked(tmp_path):
    (tmp_path / "node_modules/pkg").mkdir(parents=True)
    (tmp_path / "node_modules/pkg/index.js").write_text("// vendored\n")
    (tmp_path / "app.js").write_text("// ours\n")
    scanned = project.scan(tmp_path)
    assert "app.js" in scanned.files
    assert not any(f.startswith("node_modules/") for f in scanned.files)


def test_environment_reads_are_found_across_languages(tmp_path):
    (tmp_path / "a.py").write_text('import os\nos.getenv("PY_VAR")\n')
    (tmp_path / "b.js").write_text("const x = process.env.NODE_VAR;\n")
    (tmp_path / "c.rb").write_text('ENV["RUBY_VAR"]\n')
    (tmp_path / "d.sh").write_text('echo "$SHELL_VAR"\n')
    found = project.scan(tmp_path).env_names
    assert {"PY_VAR", "NODE_VAR", "RUBY_VAR", "SHELL_VAR"} <= found


def test_a_broken_pyproject_does_not_stop_the_scan(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project\nname = oops\n")
    (tmp_path / "Makefile").write_text("test:\n\techo hi\n")
    scanned = project.scan(tmp_path)
    assert scanned.extras == set()
    assert scanned.make_targets == {"test"}


def test_a_leading_dot_slash_is_a_prefix_not_a_character_set():
    assert project.relative_path("./.github/ci.yml") == ".github/ci.yml"
    assert project.relative_path(".github/ci.yml") == ".github/ci.yml"
    assert project.relative_path("././a.md") == "a.md"
