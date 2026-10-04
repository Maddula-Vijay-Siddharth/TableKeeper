Tablekeeper
===========

Tablekeeper is a Python/FastAPI restaurant reservation service backed by PostgreSQL.
The booking invariant is enforced in the database: `reservation_tables` has a
PostgreSQL GiST exclusion constraint that rejects overlapping active occupied
ranges for the same table. Availability responses are advisory only.

## Requirements

- Python 3.12
- uv
- PostgreSQL 15+ with permission to create the `btree_gist` extension

## Configuration

Copy `.env.example` to `.env` or set environment variables directly.

```text
TABLEKEEPER_DATABASE_URL=postgresql+psycopg://tablekeeper:tablekeeper@localhost:5432/tablekeeper
TABLEKEEPER_IDEMPOTENCY_TTL_HOURS=48
```

For integration tests, set:

```text
TABLEKEEPER_TEST_DATABASE_URL=postgresql+psycopg://tablekeeper:tablekeeper@localhost:5432/tablekeeper_test
```

## Clean Setup

```powershell
uv sync --dev
uv run tablekeeper-migrate
uv run tablekeeper-api
```

The API listens on `http://127.0.0.1:8000` by default. Protected routes use
`X-User-Id: <uuid>` for the current implementation's lightweight identity.

## Validation

```powershell
uv run pytest -q
python -m compileall src tests
```

PostgreSQL-backed tests are skipped unless `TABLEKEEPER_TEST_DATABASE_URL` is
set. Those tests exercise the exclusion constraint, including exact adjacency
and rejected overlaps.
