## What and why

## How it's tested

## Checklist

- [ ] `uv run ruff check .` and `uv run ruff format --check src tests example`
- [ ] `uv run mypy src`
- [ ] `uv run pytest --cov=django_event_bus --cov-report=term-missing`
- [ ] `uv run pytest -m integration` (needs `docker compose -f example/docker-compose.yml up -d redis`)
- [ ] `CHANGELOG.md`/`CHANGELOG.fr.md` updated if the public behavior changes
