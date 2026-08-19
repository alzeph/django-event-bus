# Contributing to django-event-bus

English · [Français](CONTRIBUTING.fr.md)

Thanks for wanting to contribute! This guide describes how to set up the
development environment and what's expected for a pull request.

## Setup

The project uses [uv](https://docs.astral.sh/uv/) for dependency and
virtual environment management.

```bash
uv sync --group dev
```

## Checks before opening a PR

```bash
uv run ruff check .
uv run ruff format --check src tests example
uv run mypy src
uv run pytest --cov=django_event_bus --cov-report=term-missing

# Needs a running Redis (docker compose -f example/docker-compose.yml up -d redis):
uv run pytest -m integration
```

These same checks run in CI (`.github/workflows/ci.yml`) and must all pass
before a PR is mergeable:

- **ruff**: lint (PEP 8, PEP 257/pydocstyle, import order, naming) and
  formatting.
- **mypy** (with `django-stubs`): typing must stay precise across `src/`.
- **pytest**, against Django 4.2/5.0/5.1/5.2/6.0/6.1 (SQLite). Unit tests
  run without any external service (`LocMemBroker`, a `FakeTransport`, an
  in-memory gRPC server); a separate job runs the `-m integration` suite
  against a real Redis service container.

If `pre-commit` is installed (`uv run pre-commit install`), ruff and mypy
run automatically before each commit.

## Compatibility

`django-event-bus` targets **Python 3.13+** and **Django 4.2+** (current
LTS and later versions). Any PR must remain compatible with these minimum
versions.

## Code style

- No comment that explains the *what* (the code should be readable on its
  own) — only the *why* when it's non-obvious (a hidden constraint, a
  subtle invariant, a workaround for a specific bug).
- No comment that narrates the editing process ("new", "already in
  place", "unlike a previous version...") — a comment describes the code
  as it stands, not how it got there.
- No abstraction or feature added beyond what a change requires. A broker,
  a transport, or a resource serializer only grows a new option when a
  real use case needs it.
- Docstrings on public modules/classes/functions are bilingual: a French
  paragraph, then its English translation, in that order (see any file
  under `src/django_event_bus/` for the convention). Inline comments stay
  in French, except where they explain a genuinely non-obvious technical
  choice.
- Any new broker/transport must implement the full `BaseBroker`/
  `BaseTransport` interface (`brokers/base.py`, `remote/transports/base.py`)
  and be resilient to transient network errors the same way
  `RedisStreamsBroker` is (see its docstring) — a worker or a
  `RemoteForeignKey` resolution should not crash on a temporary network
  blip.

## Commits and PRs

- A clear commit message that explains the *why* of the change.
- One PR = one topic. Prefer several small PRs over a single catch-all PR.
- Describe what changes and how it's tested in the PR description.
- Update `CHANGELOG.md` (and `CHANGELOG.fr.md`) if the change affects the
  public API.

## Compatibility and deprecation policy

`django-event-bus` follows [Semantic Versioning](https://semver.org/). The
project is currently in *release candidate* phase (`1.0.0rcN`): the API is
considered frozen but has not yet been battle-tested by real-world usage
outside this repository — breaking changes are still possible between
release candidates if a design flaw is found, but are avoided where
possible.

From `1.0.0` onward:

- a **major** (`X.0.0`) can break compatibility;
- a **minor** (`1.X.0`) adds features without breaking anything;
- a **patch** (`1.0.X`) only contains bug fixes.

After `1.0.0`, any deprecated public API keeps working and raises an
explicit `DeprecationWarning` for at least one full minor version before
being removed in a subsequent major.

## Reporting a bug or proposing a feature

Open an [issue](https://github.com/alzeph/django-event-bus/issues) using
the appropriate template. For a security vulnerability, see
[SECURITY.md](SECURITY.md) instead of a public issue.
