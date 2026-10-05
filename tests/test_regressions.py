"""Cases taken from real repositories, kept because each one cost precision.

The first is the bug that started the project. The rest are false alarms the
checker produced on documentation that was correct, which is the failure that
gets a linter deleted rather than fixed.
"""

from sahih import document, project
from sahih.claims import Kind, Status
from sahih.extract import from_document
from sahih.verify import verify


def run(text, root):
    scanned = project.scan(root)
    parsed = document.read("README.md", text)
    return verify(from_document(parsed, scanned), scanned)


def failures(results):
    return [r for r in results if r.status is Status.FAILS]


def test_a_heading_naming_the_real_path_does_not_excuse_the_command_below_it(repo):
    """deploy-forge: the heading said scripts/deploy.sh and the command said ./deploy.sh."""
    text = (
        "## `scripts/deploy.sh`\n"
        "\n"
        "```bash\n"
        "DEMO_ROOT=/var/www/myapp \\\n"
        "  ./deploy.sh\n"
        "```\n"
    )
    broken = failures(run(text, repo))
    assert [r.claim.subject for r in broken] == ["deploy.sh"]
    assert broken[0].evidence == "scripts/deploy.sh"


def test_a_table_describing_a_deployment_target_is_not_about_this_repository(repo):
    """deploy-forge: releases/ and shared/ live on the server, not in the repo."""
    text = "| `APP_ROOT` | *required* | Deployment root holding `releases/`, `shared/` |\n"
    assert failures(run(text, repo)) == []


def test_an_absolute_path_in_prose_is_not_a_repository_claim(repo):
    """deploy-forge: a full /var is a statement about the machine."""
    assert failures(run("a full `/var` is invisible to `df /`\n", repo)) == []


def test_paths_inside_the_software_being_inspected_are_not_claims(repo):
    """wp-sentinel: a scanner names paths in the site it scans."""
    text = "It checks `wp-content/debug.log`, `wp-admin/install.php` and `wp-cron.php`.\n"
    results = run(text, repo)
    assert failures(results) == []
    assert all(r.status is Status.UNDECIDED for r in results)


def test_a_flag_belonging_to_someone_elses_program_is_not_claimed(repo):
    """sentinel-audit: an example showed `if myservice --check-tls`."""
    text = "```bash\nif myservice --check-tls >/dev/null 2>&1; then echo ok; fi\n```\n"
    results = run(text, repo)
    assert not any(r.claim.kind is Kind.OPTION for r in results)


def test_a_flat_layout_package_is_not_reported_as_missing(tmp_path):
    """A src-layout assumption turned every flat package into a false alarm."""
    (tmp_path / "tool").mkdir()
    (tmp_path / "tool/__init__.py").write_text("")
    (tmp_path / "tool/__main__.py").write_text("")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "tool"\n')
    assert failures(run("```bash\npython3 -m tool\n```\n", tmp_path)) == []
