# Changelog

English · [Français](CHANGELOG.fr.md)

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.0rc2] - 2026-08-19

### Added

- **Optional shared-secret auth**: `REMOTE_DATA["AUTH_TOKEN"]`, checked by
  `resource_detail` (401 if missing/wrong) and a new gRPC interceptor
  (`UNAUTHENTICATED`); the HTTP and gRPC transports attach it
  automatically from `auth_token` in the matching `SERVICE_REGISTRY`
  entry.
- **TLS for gRPC**: `remote.grpc_server.serve()` accepts `credentials`
  (`grpc.ServerCredentials`, served via `add_secure_port`), wired from
  `manage.py remote_grpc_server` via
  `REMOTE_DATA["GRPC_SERVER_CREDENTIALS"]`; `GRPCTransport` opens an
  encrypted channel when `credentials` is set in `SERVICE_REGISTRY`.
- `serve()` accepts an `interceptors` sequence, so a custom gRPC rate
  limiter (or any other interceptor) can be plugged in without forking
  the server.
- `resource_detail` now explicitly restricts the HTTP method to `GET`
  (`@require_GET`).
- `expose_resource` now detects, at load time, a relation field
  (`ForeignKey`) listed without a `get_<field>` method, instead of a late
  `TypeError` at JSON-encoding time on the first request.
- `RedisStreamsBroker` accepts a `MAXLEN` option to bound the business
  and dead-letter streams' length (`XADD ... MAXLEN ~`).
- CI: a `security` job (`pip-audit`, advisory — not blocking `build`)
  and a dedicated CodeQL workflow for Python.

### Fixed

- `HTTPTransport`/`GRPCTransport`: an invalid JSON response body now
  raises `RemoteServiceUnavailableError`, like other unreachable/error
  responses, instead of an unhandled decoding exception.
- `RedisStreamsBroker`: recreating a consumer group lost to a `NOGROUP`
  error (manual removal, ops mistake) no longer replays the stream's
  entire history — it resumes from new messages only.
- `ResourceSerializer.to_representation`: exposing a relation field
  without a `get_<field>` method now raises a clear
  `ImproperlyConfiguredError` instead of a `TypeError` at JSON encoding.
- `dispatcher.dispatch`: a partial receiver failure now logs that the
  redelivery will re-run every receiver for the event, including the
  ones that already succeeded.

## [1.0.0rc1] - 2026-08-18

### Added

- **Event bus**: `RemoteSignal` (emission) and `@receiver(event_type)`
  (subscription by event name, not by importing the emitting service's
  Python object — the whole point of two services not knowing each
  other's code). `events.py` files are auto-discovered in every
  installed app at startup, the same mechanism as `admin.autodiscover()`.
- Two interchangeable broker backends behind `EVENT_BUS["BACKEND"]`:
  `LocMemBroker` (default, in-process, no infra — for tests/dev) and
  `RedisStreamsBroker` (Redis Streams + consumer groups: durable,
  at-least-once delivery, several workers of the same service can share
  a group, automatic retry then dead-letter after `MAX_RETRIES`, and
  resilience to transient network/connection errors on the blocking
  read).
- `manage.py eventbus_worker`: blocking command that consumes every
  `event_type` with a local `@receiver`, acknowledges on success,
  retries then dead-letters on failure.
- `RemoteSignal.send()` publishes via `transaction.on_commit()`: an
  event is only sent once the enclosing transaction actually commits,
  never for a row whose write was rolled back.
- **`RemoteForeignKey`**: a model field resolving a remote service's
  data from a locally stored PK — a plain integer column
  (`makemigrations`/`migrate` work normally), an accessor derived from
  the field name (`user_id` → `user`, like a regular `ForeignKey`),
  lazy resolution through the Django cache then, on a miss, the
  configured transport (HTTP or gRPC). A 404 on the source service
  resolves to `None`; a network failure raises
  `RemoteServiceUnavailableError` rather than failing silently.
  `invalidate_on=[...]` reuses the event bus to delete the matching
  cache entry as soon as the source service publishes one of the listed
  events.
- **`@expose_resource`** / `ResourceSerializer`: a Django REST
  Framework-style declarative way to expose a model to
  `RemoteForeignKey` — `Meta.model`/`Meta.resource`/`fields`
  (`"__all__"` or an explicit list) /`exclude`, `get_<field>` methods
  for computed fields (the `SerializerMethodField` convention),
  `get_queryset()`/`to_representation()` overridable for full control.
  A single declaration answers both HTTP (`django_event_bus.remote.urls`,
  one `include()`) and gRPC (`REMOTE_DATA["GRPC_RESOLVER"]` defaults to
  the generic resolver built from this registry).
- Generic gRPC contract (`remote/proto/remote_resource.proto`): a
  single `GetResource(resource, pk)` RPC so that no service has to
  write its own `.proto`. The payload is carried as JSON rather than
  `google.protobuf.Struct` — `Struct` only has a `double` numeric type
  and would silently turn integers into floats (precision loss beyond
  2^53); JSON preserves `int`/`float` like the HTTP transport does.
  `manage.py remote_grpc_server` starts the server side.
- A two-service demo (`example/`) exercising every feature in both
  directions (`service_auth` ⇄ `service_order`), with real web
  dashboards, a `Dockerfile` and a `docker-compose.yml` bringing up the
  whole thing (Redis, migrations, HTTP/gRPC/worker processes) with a
  single `docker compose up -d --build`.
