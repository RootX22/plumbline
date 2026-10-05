from plumbline import document


def test_a_fenced_block_keeps_the_line_its_content_starts_on():
    text = "intro\n\n```bash\nmake test\n```\n"
    parsed = document.read("README.md", text)
    assert len(parsed.blocks) == 1
    assert parsed.blocks[0].lines == ("make test",)
    assert parsed.blocks[0].first_line == 4
    assert parsed.line(4) == "make test"


def test_a_block_remembers_the_heading_above_it():
    text = "## Example output\n\n```\nall good\n```\n"
    parsed = document.read("README.md", text)
    assert parsed.blocks[0].heading == "Example output"


def test_prose_excludes_fenced_content():
    parsed = document.read("README.md", "run it\n\n```\nmake test\n```\nafter\n")
    assert "make test" not in " ".join(parsed.prose.values())
    assert any("after" in line for line in parsed.prose.values())


def test_inline_code_and_links_carry_their_line():
    text = "see `docs/setup.md` and [the guide](docs/setup.md)\n"
    parsed = document.read("README.md", text)
    assert document.inline_code(parsed) == [(1, "docs/setup.md")]
    assert document.links(parsed) == [(1, "docs/setup.md")]


def test_a_quote_can_be_located_for_citation():
    parsed = document.read("README.md", "first\nthe worker reads DEMO_ROOT\n")
    assert parsed.quotes("reads DEMO_ROOT") == [2]
    assert parsed.quotes("never written") == []


def test_an_unclosed_fence_still_yields_its_content():
    parsed = document.read("README.md", "```bash\nmake test\n")
    assert parsed.blocks[0].lines == ("make test",)
