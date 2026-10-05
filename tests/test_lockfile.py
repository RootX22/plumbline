from plumbline import lockfile
from plumbline.claims import Claim, Kind, Source


def entry(subject="DEMO_ROOT"):
    return lockfile.Entry(
        digest=lockfile.digest("hello"),
        claims=[Claim(kind=Kind.ENV, subject=subject, line=4,
                      quote=f"reads {subject}", source=Source.MODEL)])


def test_claims_survive_a_round_trip(tmp_path):
    path = tmp_path / ".plumbline/claims.json"
    lockfile.save(path, {"README.md": entry()})
    loaded = lockfile.load(path)
    assert loaded["README.md"].claims[0].subject == "DEMO_ROOT"
    assert loaded["README.md"].claims[0].source is Source.MODEL
    assert loaded["README.md"].digest == lockfile.digest("hello")


def test_the_file_is_sorted_so_a_diff_is_readable(tmp_path):
    path = tmp_path / "claims.json"
    lockfile.save(path, {"b.md": entry(), "a.md": entry()})
    body = path.read_text()
    assert body.index('"a.md"') < body.index('"b.md"')


def test_a_missing_or_damaged_file_loads_as_empty(tmp_path):
    assert lockfile.load(tmp_path / "absent.json") == {}
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    assert lockfile.load(broken) == {}


def test_a_file_from_another_version_is_ignored(tmp_path):
    path = tmp_path / "claims.json"
    path.write_text('{"version": 99, "documents": '
                    '{"README.md": {"digest": "x", "claims": []}}}')
    assert lockfile.load(path) == {}


def test_a_claim_with_an_unknown_kind_is_dropped_on_load(tmp_path):
    path = tmp_path / "claims.json"
    path.write_text('{"version": 1, "documents": {"R.md": {"digest": "x", "claims": ['
                    '{"kind": "weather", "subject": "rain", "line": 1, "quote": "rain"}]}}}')
    assert lockfile.load(path)["R.md"].claims == []
