"""The gate between what a model says and what gets checked.

These are the tests that matter most. Everything else decides whether a claim
is true; this decides whether a claim is allowed to exist, and it is the only
thing standing between an invented sentence and a report that looks official.
"""

import json

from sahih import document
from sahih.claims import Kind, Source
from sahih.model import ModelUnavailable, Ollama, admit, numbered_prose, read_prose

TEXT = (
    "# demo\n"
    "\n"
    "The worker reads DEMO_ROOT before it starts.\n"
    "Configuration lives in docs/setup.md.\n"
    "\n"
    "```bash\n"
    "make test\n"
    "```\n"
)


class Stub:
    def __init__(self, payload):
        self.payload = payload
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        return self.payload


def parsed():
    return document.read("README.md", TEXT)


def test_a_claim_quoting_the_document_is_admitted():
    claims = admit([{"kind": "env", "subject": "DEMO_ROOT", "line": 3,
                     "quote": "The worker reads DEMO_ROOT before it starts."}], parsed())
    assert [c.subject for c in claims] == ["DEMO_ROOT"]
    assert claims[0].source is Source.MODEL
    assert claims[0].kind is Kind.ENV


def test_a_quote_that_appears_nowhere_is_refused():
    claims = admit([{"kind": "env", "subject": "SECRET_KEY", "line": 3,
                     "quote": "The worker reads SECRET_KEY before it starts."}], parsed())
    assert claims == []


def test_a_subject_absent_from_its_own_quote_is_refused():
    claims = admit([{"kind": "env", "subject": "OTHER_VAR", "line": 3,
                     "quote": "The worker reads DEMO_ROOT before it starts."}], parsed())
    assert claims == []


def test_a_line_number_that_is_slightly_off_is_corrected_not_trusted():
    claims = admit([{"kind": "env", "subject": "DEMO_ROOT", "line": 9,
                     "quote": "The worker reads DEMO_ROOT before it starts."}], parsed())
    assert [c.line for c in claims] == [3]


def test_a_kind_with_no_verifier_is_refused():
    claims = admit([{"kind": "uptime", "subject": "99.99%", "line": 3,
                     "quote": "The worker reads DEMO_ROOT before it starts."}], parsed())
    assert claims == []


def test_a_claim_citing_fenced_content_is_left_to_the_extractor():
    claims = admit([{"kind": "make", "subject": "test", "line": 7,
                     "quote": "make test"}], parsed())
    assert claims == []


def test_malformed_output_yields_nothing_rather_than_raising():
    assert read_prose(parsed(), Stub("I could not find any claims.")) == []
    assert read_prose(parsed(), Stub("")) == []
    assert read_prose(parsed(), Stub("[{oops}]")) == []


def test_output_wrapped_in_prose_is_still_read():
    payload = ('Here is the result:\n'
               '[{"kind": "path", "subject": "docs/setup.md", "line": 4,'
               ' "quote": "Configuration lives in docs/setup.md."}]\n'
               'Hope that helps.')
    claims = read_prose(parsed(), Stub(payload))
    assert [c.subject for c in claims] == ["docs/setup.md"]


def test_the_model_is_shown_prose_and_not_fenced_commands():
    stub = Stub("[]")
    read_prose(parsed(), stub)
    assert "make test" not in stub.prompts[0]
    assert "The worker reads DEMO_ROOT" in stub.prompts[0]


def test_prose_is_numbered_so_a_citation_can_be_located():
    numbered = numbered_prose(parsed())
    assert "3: The worker reads DEMO_ROOT before it starts." in numbered


def test_no_admitted_claim_carries_a_verdict():
    claims = admit([{"kind": "env", "subject": "DEMO_ROOT", "line": 3, "status": "holds",
                     "quote": "The worker reads DEMO_ROOT before it starts."}], parsed())
    assert not hasattr(claims[0], "status")


def test_an_unreachable_endpoint_is_reported_rather_than_swallowed():
    client = Ollama(endpoint="http://127.0.0.1:9", timeout=0.3)
    try:
        client.generate("anything")
    except ModelUnavailable as error:
        assert "did not answer" in str(error)
    else:
        raise AssertionError("an unreachable endpoint should raise")


def test_the_request_pins_the_model_to_one_answer(monkeypatch):
    """A linter that disagrees with itself between runs is not a linter."""
    captured = {}

    class Response:
        def read(self):
            return b'{"response": "[]"}'

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode())
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    Ollama(model="llama3").generate("anything")

    assert captured["url"].endswith("/api/generate")
    assert captured["body"]["options"]["temperature"] == 0.0
    assert captured["body"]["stream"] is False
    assert captured["body"]["model"] == "llama3"
