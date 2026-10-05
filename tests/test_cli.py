import json

from plumbline import lockfile, model
from plumbline.claims import Claim, Kind, Source
from plumbline.cli import EXIT_FAILED_CLAIMS, EXIT_OK, EXIT_USAGE, main


def write(repo, text):
    (repo / "README.md").write_text(text)


def test_a_document_whose_claims_hold_exits_zero(repo, capsys):
    write(repo, "```bash\nmake test\n```\n")
    assert main(["check", "--root", str(repo), "README.md"]) == EXIT_OK
    assert "1 hold" in capsys.readouterr().out


def test_a_broken_claim_exits_one_and_names_the_line(repo, capsys):
    write(repo, "Run it:\n\n```bash\n./deploy.sh\n```\n")
    assert main(["check", "--root", str(repo), "README.md"]) == EXIT_FAILED_CLAIMS
    out = capsys.readouterr().out
    assert "line 4" in out
    assert "scripts/deploy.sh" in out


def test_json_output_is_machine_readable(repo, capsys):
    write(repo, "```bash\n./deploy.sh\nmake test\n```\n")
    main(["check", "--root", str(repo), "README.md", "--json"])
    payload = json.loads(capsys.readouterr().out)
    statuses = {c["subject"]: c["status"] for c in payload["documents"][0]["claims"]}
    assert statuses["deploy.sh"] == "fails"
    assert statuses["test"] == "holds"


def test_unchecked_claims_are_hidden_unless_asked_for(repo, capsys):
    write(repo, "see `wp-content/debug.log`\n")
    main(["check", "--root", str(repo), "README.md"])
    assert "debug.log" not in capsys.readouterr().out

    main(["check", "--root", str(repo), "README.md", "--show-unchecked"])
    assert "debug.log" in capsys.readouterr().out


def test_a_missing_root_is_a_usage_error(tmp_path, capsys):
    assert main(["check", "--root", str(tmp_path / "nowhere")]) == EXIT_USAGE


def test_recorded_claims_are_verified_without_a_model(repo, capsys):
    write(repo, "The worker reads DEMO_OLD at boot.\n")
    entry = lockfile.Entry(
        digest=lockfile.digest((repo / "README.md").read_text()),
        claims=[Claim(kind=Kind.ENV, subject="DEMO_OLD", line=1,
                      quote="The worker reads DEMO_OLD at boot.", source=Source.MODEL)])
    lockfile.save(repo / ".plumbline/claims.json", {"README.md": entry})

    assert main(["check", "--root", str(repo), "README.md"]) == EXIT_FAILED_CLAIMS
    out = capsys.readouterr().out
    assert "[model]" in out
    assert "DEMO_OLD" in out


def test_claims_recorded_against_an_older_document_are_not_trusted(repo, capsys):
    write(repo, "The worker reads DEMO_OLD at boot.\n")
    entry = lockfile.Entry(digest="0000000000000000",
                           claims=[Claim(kind=Kind.ENV, subject="DEMO_OLD", line=1,
                                         quote="x", source=Source.MODEL)])
    lockfile.save(repo / ".plumbline/claims.json", {"README.md": entry})

    assert main(["check", "--root", str(repo), "README.md"]) == EXIT_OK
    assert "older than the document" in capsys.readouterr().err


def test_a_directory_is_walked_for_markdown(repo, capsys):
    (repo / "docs/extra.md").write_text("```bash\n./deploy.sh\n```\n")
    assert main(["check", "--root", str(repo), "docs"]) == EXIT_FAILED_CLAIMS
    assert "docs/extra.md" in capsys.readouterr().out


def test_extract_records_what_the_model_found(repo, capsys, monkeypatch):
    write(repo, "The worker reads DEMO_OLD at boot.\n")

    class Stub:
        def __init__(self, *_, **__):
            pass

        def generate(self, prompt):
            return ('[{"kind": "env", "subject": "DEMO_OLD", "line": 1, '
                    '"quote": "The worker reads DEMO_OLD at boot."}]')

    monkeypatch.setattr("plumbline.cli.model.Ollama", Stub)
    assert main(["extract", "--root", str(repo), "README.md"]) == EXIT_OK

    recorded = lockfile.load(repo / ".plumbline/claims.json")
    assert [c.subject for c in recorded["README.md"].claims] == ["DEMO_OLD"]
    assert "1 claims recorded" in capsys.readouterr().out


def test_extract_reports_an_unreachable_model_instead_of_writing_nothing(repo, monkeypatch):
    write(repo, "The worker reads DEMO_OLD at boot.\n")

    class Dead:
        def __init__(self, *_, **__):
            pass

        def generate(self, prompt):
            raise model.ModelUnavailable("localhost did not answer")

    monkeypatch.setattr("plumbline.cli.model.Ollama", Dead)
    assert main(["extract", "--root", str(repo), "README.md"]) == EXIT_USAGE
    assert not (repo / ".plumbline/claims.json").exists()


def test_extract_without_documents_is_a_usage_error(tmp_path):
    assert main(["extract", "--root", str(tmp_path), "absent.md"]) == EXIT_USAGE


def test_no_subcommand_prints_help(capsys):
    assert main([]) == EXIT_USAGE
    assert "plumbline" in capsys.readouterr().out
