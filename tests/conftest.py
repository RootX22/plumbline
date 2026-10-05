import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def repo(tmp_path):
    """A small repository with the shapes the verifiers look for."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/deploy.sh").write_text("#!/bin/sh\necho deploying\n")
    (tmp_path / "scripts/rollback.sh").write_text("#!/bin/sh\necho rolling back\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/setup.md").write_text("# setup\n")
    (tmp_path / "Makefile").write_text(
        "SHELL := /bin/sh\n\n.PHONY: test\ntest:\n\tpytest -q\n\nlint:\n\truff check .\n")
    (tmp_path / "package.json").write_text(
        '{"name":"demo","scripts":{"build":"tsc","start":"node ."}}')
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\n\n[project.optional-dependencies]\ndev = ["pytest"]\n')
    (tmp_path / "compose.yml").write_text(
        "services:\n  api:\n    image: demo\n  worker:\n    image: demo\n")
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo/__init__.py").write_text("")
    (tmp_path / "demo/__main__.py").write_text("")
    (tmp_path / "demo/cli.py").write_text(
        'import os\n\nFLAG = "--json"\nROOT = os.getenv("DEMO_ROOT")\n')
    return tmp_path
