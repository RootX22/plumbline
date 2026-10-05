# plumbline

Documentation is a set of claims about a repository. Nothing checks them.

A README says a file is there, a command works, a variable is read. Those are
assertions, as testable as anything in a test suite, and they are the only part
of a project that nobody runs. So they rot, quietly, and the first person to
find out is whoever is following them at two in the morning, or on their first
day, or while deciding whether the project is worth their time.

`plumbline` reads a document, pulls out every claim it can check, and checks it.

## The bug that started it

A deployment toolkit of mine had this in its README:

<!-- plumbline:ignore -->
```bash
## `scripts/deploy.sh`

APP_ROOT=/var/www/myapp \
  ./deploy.sh
```

The heading is right. The command is wrong, and it had been wrong since the
scripts were moved into `scripts/`. Every copy-pasteable line in that file
failed with `No such file or directory`, which is the first thing anyone
evaluating the project would have hit. Nothing caught it, because nothing was
looking: linters check whether Markdown is well formed, not whether it is true.

## Install

```bash
pip install git+https://github.com/RootX22/plumbline.git
```

## Use

```bash
plumbline check
```

With no arguments it reads `README.md`, `CONTRIBUTING.md`, `RUNBOOK.md` and
anything under `docs/`, and exits non-zero if a claim fails.

```text
README.md
  line 41: script to run deploy.sh  [doc]
    ./deploy.sh will not run from the repository root; the script is at scripts/deploy.sh
    said: APP_ROOT=/var/www/myapp   ./deploy.sh
    nearest: scripts/deploy.sh
  16 hold, 3 fail, 0 unchecked
```

`--json` for a machine, `--show-unchecked` to see what it declined to judge,
`--root` to point at a repository that is not the working directory.

A document that quotes another project's commands, or shows a deliberately
broken one, says so:

```markdown
<!-- plumbline:ignore -->
```

on the line above a fenced block, or at the end of a prose line, and that block
or line is left alone. The example further up this file carries one.

## What it checks

| Claim | Checked against |
| --- | --- |
| a script you are told to run | the path, as spelled, from the repository root |
| `make <target>` | the targets a Makefile defines |
| `npm run <script>` | the scripts `package.json` declares |
| `python -m <module>` | an importable package with a `__main__.py`, flat layout or `src` |
| `pip install ".[extra]"` | the optional-dependency groups in `pyproject.toml` |
| `docker compose up <service>` | the services a compose file defines |
| a command-line flag | the long options the source actually defines |
| `VAR=value cmd` | whether anything in the repository reads `VAR` |
| a relative link | the file it points at |
| a path in backticks | the repository, relative to the document |

## Where the model comes in

A fenced command is unambiguous, and the extractor finds it with no help. The
claims that hurt people are written as English: *the worker reads `QUEUE_URL`*,
*credentials live in `config/secrets.yml`*, *run the migration before starting
the consumer*. Finding those in prose is what a language model is genuinely
better at than a pattern.

What the model is not allowed to do is decide whether a claim is true.

```bash
plumbline extract            # a local model reads the prose, writes .plumbline/claims.json
plumbline check              # verifies that file against the repository, calling nothing
```

Two properties fall out of that split, and both are the point rather than a
detail:

**A hallucinated claim cannot pass.** Every candidate the model returns must
quote the document word for word, and must name its subject inside its own
quote. A claim about a file the document never mentions fails to cite anything
and is dropped before a verifier ever sees it. A claim that survives is then
checked against the filesystem like any other, so an invented one fails loudly
rather than passing quietly.

**The verdict does not move when the model does.** Swap the model, change the
temperature, run it again on a Tuesday: that can change *which* claims are
found. It cannot change the answer for a claim already found, because the
answer comes from the repository. Continuous integration runs `check`, which
reads a recorded file and talks to nothing. Refreshing those claims is a
deliberate act with a diff to review, which is also the only time anyone has to
have a model installed.

The model is reached over Ollama's HTTP API on `localhost`, because linting a
private repository's documentation is a poor reason to send its internals to a
third party. `--model` and `--endpoint` change that if you want something else;
anything with a `generate` method returning text will do.

## Saying "I don't know"

Three answers, not two: a claim holds, fails, or could not be decided.

That third answer is the whole difference between a checker people keep and one
they uninstall in a week. A repository with no Makefile has not disproved a
claim about a make target — it has failed to check it, and saying so costs
nothing while guessing costs all the trust the tool has. Unchecked claims are
counted in the summary and shown with `--show-unchecked`.

The same reasoning drives what is deliberately *not* claimed. A scanner's
README names paths inside the site it scans. A deployment guide names
directories on the target server. An example shows somebody else's program
taking a flag. None of those are assertions about this repository, and a
checker that reports them is wrong in the way that matters most, because the
person reading the report cannot tell the real finding from the noise.

So: absolute paths are ignored, a bare `releases/` with no path in it is
ignored, a flag is only claimed for a command the repository actually provides,
and a path under a directory this repository does not have is reported as
undecided rather than broken.

## In CI

```yaml
- run: pip install git+https://github.com/RootX22/plumbline.git
- run: plumbline check
```

Exit codes: `0` everything checked holds, `1` at least one claim failed, `2` bad
usage. This repository runs it on its own README in `.github/workflows/ci.yml`,
on the view that a tool which cannot keep its own documentation true has no
standing to check anyone else's.

## Where it stops being reliable

* **Compose files are read by indentation, not parsed as YAML.** Service names
  under a top-level `services:` key are found. Anchors, merge keys and multiple
  files composed together are not, and will show up as undecided.
* **Shell parsing stops at the interesting cases.** Commands inside `$(...)`,
  behind `eval`, or built from variables are not followed. A command spelled
  `$DEPLOY_SCRIPT` is invisible.
* **Environment variables are only claimed where the document is unambiguous**:
  set in front of a command you are told to run, or named in prose by the model.
  A variable mentioned in passing is not treated as a claim, which means genuine
  dead configuration can slip through.
* **"Nothing reads this variable" is a lexical judgement.** Names assembled at
  runtime, read through a wrapper, or loaded from a framework's configuration
  layer will look unread when they are not.
* **Only long options are checked.** `-v` is too short to attribute to a
  particular program with any confidence.
* **Markdown only.** reStructuredText, AsciiDoc and wiki pages are not read.
* **It cannot tell you what is missing.** Every claim in the document gets
  checked; a step that was never written down is not a claim, and no amount of
  checking will find it.

## Name

A plumb line is the oldest instrument for testing whether something is *true*.
A weight on a string, hung against a wall: the wall either agrees with gravity
or it does not, and no amount of confidence on the builder's part changes the
reading. Documentation is the same kind of problem. It is either true of the
repository or it is not, and the only way to find out is to hold it up against
something that cannot be argued with.

## Development

```bash
pip install -e ".[dev]"
pytest -q
ruff check .
```

The checker has no runtime dependencies. `plumbline/extract.py` turns a document
into claims, `plumbline/verify.py` decides them, and `plumbline/model.py` holds the
gate between what a model says and what is allowed to count.

## Licence

MIT.
