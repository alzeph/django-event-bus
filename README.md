# django-event-bus

English · [Français](README.fr.md)

[![CI](https://github.com/alzeph/django-event-bus/actions/workflows/ci.yml/badge.svg)](https://github.com/alzeph/django-event-bus/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/django-event-bus.svg)](https://pypi.org/project/django-event-bus/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](pyproject.toml)

> **Release candidate.** `django-event-bus` is at `1.0.0rc1`: the API is
> considered frozen but has not yet been battle-tested by real-world usage
> outside this repository. Feedback (issues, use cases, bugs) is welcome
> before the final `1.0.0` is tagged.

## The problem this solves

In a Django microservices architecture (`service_auth`, `service_order`,
`service_product`, ...), two needs keep coming up:

1. **Notify other services** that a business event happened (a user
   created, an order paid, ...) — without each service having to configure
   Redis/Kafka itself, or know who's listening.
2. **Read data owned by another service** from its PK (a user's email to
   display an order, for instance) — without hand-writing an HTTP client
   or knowing that service's URL.

`django-event-bus` answers both with the same philosophy as Django
itself: declarative configuration in `settings.py` (`EVENT_BUS`,
`REMOTE_DATA` — like `DATABASES` or `CACHES`) and auto-discovered file
conventions (`events.py`, `resources.py` — like `admin.py`), so a service
has almost nothing but declarations to write, never network plumbing.

This README is a guided tour: each section explains *why* a piece exists
before showing *how* to use it. The `example/` folder contains two real
Django mini-projects (`service_auth`, `service_order`) that run
everything described here — the
[Two-service demo](#two-service-demo-try-it-all-for-real) section gives
the exact commands to run.

## Installation

```python
INSTALLED_APPS = [
    ...,
    "django_event_bus",
]
```

That's it for installation: no migration of its own, no model. The rest
of this README explains the two optional settings (`EVENT_BUS`,
`REMOTE_DATA`) and the file conventions they activate.

## 1. Emitting and receiving events

### Configuring the bus

```python
EVENT_BUS = {
    "SERVICE_NAME": "service_auth",  # required: identifies this service in logs/errors
    "BACKEND": "django_event_bus.brokers.redis_streams.RedisStreamsBroker",
    "OPTIONS": {"URL": "redis://localhost:6379/0"},
}
```

`BACKEND` is the only place where the broker is chosen. The default
backend, `django_event_bus.brokers.locmem.LocMemBroker`, needs no infra
(useful in tests/dev — it's what's used if you don't set `EVENT_BUS` at
all, except `SERVICE_NAME` which stays required). Switching to Redis, or
tomorrow to another broker implementing the same interface, changes
**only** this dict — no application code to touch.

### Emitting an event

```python
# accounts/events.py
from django_event_bus import RemoteSignal

# Declared once at module level, like a django.dispatch.Signal.
user_created = RemoteSignal("auth.user_created")

# Then, anywhere (a view, a post_save signal, a task, ...):
user_created.send(payload={"id": user.id, "email": user.email})
```

The `"{service}.{event}"` naming convention (`auth.user_created`) avoids
collisions between services: each one prefixes its events with its own
name.

### Receiving an event (in another service)

```python
# orders/events.py
from django_event_bus import receiver

@receiver("auth.user_created")
def on_user_created(payload, envelope, **kwargs):
    ...
```

Any `events.py` file in an installed app is auto-discovered at startup
(the same mechanism as `admin.autodiscover()` — nothing to manually
import elsewhere). Subscription happens **by event name**
(`"auth.user_created"`), never by importing the emitting service's
`RemoteSignal` object: `service_order` generally has no access to
`service_auth`'s code, so that would be impossible anyway. This rule —
subscribing to a name, not a Python object — is what lets two services
talk without knowing each other.

### Consuming events: the worker

```
python manage.py eventbus_worker
```

Starts a blocking worker that consumes the `event_type`s with a local
`@receiver` in this service, runs the receivers, acknowledges on success,
retries on failure, then moves the event to dead-letter (`{stream}:dlq`)
after `MAX_RETRIES` attempts (Redis backend). It's a separate process,
meant to run continuously (like a Celery worker) — one per service that
has at least one `@receiver`.

### `RemoteSignal.send()` and transactions

`send()` publishes via `transaction.on_commit()`: if the call happens
inside a transaction (typically a `post_save`), the event is only sent
after the actual commit — never for a row whose write was ultimately
rolled back. Outside a transaction, it's sent immediately.

**Consequence for tests**: with `pytest.mark.django_db` alone (implicit
rollback at the end of the test), the callback never fires — use
`pytest.mark.django_db(transaction=True)` (or the pytest-django
`django_capture_on_commit_callbacks` fixture) for any test that checks
an event was actually emitted.

### What the library guarantees — and what it doesn't

The bus is **at-least-once**: an event can be delivered more than once
to a `@receiver` (redelivery after a `fail()`, or after a worker crash
before the `ack`). **Write idempotent receivers** (e.g. `get_or_create`
instead of `create`, or a unique key on `envelope.event_id`).

`transaction.on_commit()` avoids "phantom" events (published for data
that was never committed) but doesn't protect against a broker outage
*at the exact moment of commit*: in that case the DB write stays
committed but the publish fails and surfaces as a post-commit error. For
a stronger zero-loss guarantee, the correct solution is a *transactional
outbox* pattern (local table + separate relay) — out of scope for this
version.

## 2. Reading data owned by another service (`RemoteForeignKey`)

### The problem, concretely

`service_order` needs to display an order's customer email. The user
lives in `service_auth`. Without this library, you'd have to write an
HTTP client, know `service_auth`'s URL, handle caching and network
failures by hand, and redo all of that for every resource.
`RemoteForeignKey` does all of it from a single declaration on the
model, the way a regular `ForeignKey` would for a local relation.

### Configuring where the other services are

```python
REMOTE_DATA = {
    "SERVICE_REGISTRY": {
        "service_auth": {
            "http": {"base_url": "http://service-auth:8000/api", "timeout": 3},
            "grpc": {"target": "service-auth:50051", "timeout": 3},
        },
    },
    "DEFAULT_TRANSPORT": "http",  # or "grpc" — see section 3
    "DEFAULT_TTL": 60,            # cache duration in seconds
}
```

**This is the only place in the project where `service_auth`'s URL
appears.** The application code (below) never knows it.

### Declaring the field

```python
# orders/models.py
from django_event_bus.remote import RemoteForeignKey

class Order(models.Model):
    user_id = RemoteForeignKey(
        service="service_auth",   # key in SERVICE_REGISTRY
        resource="users",         # must match the exposed `resource=` (section 3)
        invalidate_on=["auth.user_updated"],  # see "Invalidation" below
    )

order.user.email   # -> Django cache, otherwise HTTP/gRPC to service_auth
```

- `user_id` is a plain integer column: `makemigrations`/`migrate` work
  normally, just like any `IntegerField`.
- `order.user` — the name is derived from `user_id` by dropping the
  `_id` suffix, exactly like a Django `ForeignKey` would. If your field
  doesn't end in `_id`, the accessor becomes `{field_name}_remote` (or
  pass `accessor_name=...` explicitly).
- Accessing `order.user` **resolves lazily**: first the Django cache
  (`REMOTE_DATA["CACHE_ALIAS"]`, `locmem` by default, a real Redis cache
  in production if you configure `CACHES`), then, if missing or expired,
  the configured transport.
- Resource missing on the source service (404) → `order.user` is
  `None`, like an unresolved nullable `ForeignKey`. Service unreachable
  (network failure, timeout) → raises `RemoteServiceUnavailableError`:
  this is deliberate, unavailable data must be visible to your code, not
  hidden behind an ambiguous `None`.

> **Classic trap: the cache must be shared across processes.**
> Without an explicit `CACHES`, Django uses `locmem` — an **in-process**
> cache. A service almost always runs as several processes (the web
> server, `eventbus_worker`, `remote_grpc_server`, an occasional
> `manage.py shell`): with `locmem`, each has its own isolated memory,
> and the invalidation done by `eventbus_worker` (see "Event-driven
> invalidation" below) has **no visible effect** on the cache seen by
> the web server — silently, with no error, just data that never
> refreshes. Use a genuinely shared cache, for example Redis (Django ≥
> 4.0 ships a native backend):
> ```python
> CACHES = {
>     "default": {
>         "BACKEND": "django.core.cache.backends.redis.RedisCache",
>         "LOCATION": "redis://localhost:6379/1",
>     }
> }
> ```
> This is exactly what `example/` does (see below) — this trap was
> discovered and fixed there by verifying the demo with persistent
> processes rather than a `manage.py shell` restarted at every step
> (which hides the problem: a fresh process has a cold cache anyway).

## 3. Exposing your data (`@expose_resource`)

### The problem, concretely

The previous section assumes `service_auth` knows how to answer "here's
user number 5" over HTTP and gRPC. Without a dedicated mechanism, you'd
have to hand-write a Django view *and* a gRPC resolver function,
duplicating the same field list in both — painful as soon as a service
exposes more than one resource, and a quick source of inconsistencies
(HTTP returns a field gRPC forgot, etc.). `@expose_resource` solves this
with **a single declaration** that feeds both transports.

### Declaring a resource

```python
# accounts/resources.py — auto-discovered, like events.py
from django.contrib.auth.models import User
from django_event_bus.remote import ResourceSerializer, expose_resource

@expose_resource
class UserResourceSerializer(ResourceSerializer):
    class Meta:
        model = User
        resource = "users"  # the key expected by RemoteForeignKey(resource=...)
        fields = ["id", "username", "email", "full_name"]

    def get_full_name(self, instance):
        """Computed field: doesn't exist on the model, built on demand.

        The get_<field> convention, identical to Django REST Framework's
        SerializerMethodField — familiar if you've used DRF before.
        """
        full_name = f"{instance.first_name} {instance.last_name}".strip()
        return full_name or instance.username
```

That's it: this class now answers over HTTP and gRPC, for any service
that has `service_auth` in its `SERVICE_REGISTRY`.

### Customizing `ResourceSerializer`

| What you want to do | How |
|---|---|
| Expose every field of the model | `fields = "__all__"` (default if `fields` is omitted) |
| Expose a specific list | `fields = ["id", "email"]` |
| Expose everything except some fields | `exclude = ["password"]` (mutually exclusive with an explicit `fields`) |
| Add a computed field / rename a field | a `get_<field>(self, instance)` method — see `get_full_name` above |
| Restrict the query (visibility, `select_related`, ...) | override `get_queryset(cls)` (classmethod) |
| Full control over the output shape | override `to_representation(self, instance)` — bypasses `fields`/`get_<field>` |

```python
@expose_resource
class UserResourceSerializer(ResourceSerializer):
    class Meta:
        model = User
        resource = "users"
        exclude = ["password", "is_superuser"]

    @classmethod
    def get_queryset(cls):
        # Example: never expose deactivated accounts.
        return User.objects.filter(is_active=True).select_related(...)
```

A resource already claimed by another class raises
`ImproperlyConfiguredError` (two serializers can't fight over the same
name); a missing `Meta.model`/`Meta.resource` raises the same exception,
early, rather than a confusing error on first call.

### Wiring HTTP

```python
# service_auth/urls.py
from django.urls import include, path

urlpatterns = [
    path("api/", include("django_event_bus.remote.urls")),
]
```

One line, no matter how many resources are exposed: it serves
`GET /api/<resource>/<pk>/` for all of them, with a clean 404 if the
resource or PK is unknown.

### Wiring gRPC

No configuration needed: as soon as at least one resource is declared
via `@expose_resource`, `REMOTE_DATA["GRPC_RESOLVER"]` points by default
to the library's generic resolver. Just start the server:

```
python manage.py remote_grpc_server --port 50051
```

The gRPC contract is deliberately a single, generic one
(`GetResource(resource, pk) -> JSON`, see
`django_event_bus/remote/proto/remote_resource.proto`): no service needs
to write its own `.proto`. Data is carried as JSON rather than as
`google.protobuf.Struct` — `Struct` only has one numeric type (`double`)
and would silently turn every integer into a float (precision loss
beyond 2^53); JSON, on the other hand, distinguishes `int` from `float`,
just like the HTTP transport already does.

To switch a `RemoteForeignKey` to gRPC on the consumer side, without
changing anything on the provider side (same `@expose_resource`):

```python
REMOTE_DATA = {
    "SERVICE_REGISTRY": {"service_auth": {"grpc": {"target": "service-auth:50051"}}},
    "DEFAULT_TRANSPORT": "grpc",
}
```

### Securing the exposed endpoints

By default, neither `resource_detail` nor the gRPC server perform
authentication — see [SECURITY.md](SECURITY.md) for the full picture
(they assume a trusted private network). Three opt-in layers, usable
independently:

```python
# Provider side (service_auth)
REMOTE_DATA = {
    "AUTH_TOKEN": "a-shared-secret",              # HTTP: 401 / gRPC: UNAUTHENTICATED without it
    "GRPC_SERVER_CREDENTIALS": "accounts.tls.build_server_credentials",  # -> grpc.ServerCredentials
}

# Consumer side (service_order)
REMOTE_DATA = {
    "SERVICE_REGISTRY": {
        "service_auth": {
            "http": {"base_url": "...", "auth_token": "a-shared-secret"},
            "grpc": {"target": "...", "auth_token": "a-shared-secret", "credentials": channel_creds},
        },
    },
}
```

For rate limiting, wrap `resource_detail` yourself in your own `urls.py`
(e.g. with `django-ratelimit`) instead of including
`django_event_bus.remote.urls` as-is, and/or pass your own
`grpc.ServerInterceptor` via `manage.py remote_grpc_server`'s
`serve(..., interceptors=[...])`.

### Event-driven invalidation

```python
user_id = RemoteForeignKey(
    service="service_auth",
    resource="users",
    invalidate_on=["auth.user_updated"],
)
```

Reuses the event bus (part 1) instead of inventing a second mechanism:
when `service_auth` publishes any of the listed `event_type`s (with the
PK in `payload["id"]` — the same convention already used by
`RemoteSignal.send(payload={"id": ...})` for business events), the
matching resource's cache entry is deleted. Combined with the TTL
(`DEFAULT_TTL`), this covers two kinds of freshness: the TTL absorbs a
missed or delayed invalidation event (best effort), and the event, when
it arrives, invalidates immediately without waiting for the TTL to
expire. **This assumes a worker (`manage.py eventbus_worker`) is running
on the consumer side** — without an active worker, only the TTL applies.

## Two-service demo: try it all for real

`example/` contains `service_auth` and `service_order`, and data flows
**in both directions** — it's not just one service reading the other:

| | exposes (provider) | consumes (`RemoteForeignKey`) | events published |
|---|---|---|---|
| `service_auth` | `User` (`accounts/resources.py`, HTTP+gRPC) | `OrderBookmark.order_id` → `service_order` (`accounts/models.py`) | `auth.user_created`/`auth.user_updated` |
| `service_order` | `Order` (`orders/resources.py`, HTTP) | `Order.user_id` → `service_auth` (`orders/models.py`) | `orders.order_created`/`orders.order_updated` |

Each service also has real web pages, no shell or curl required:
`http://localhost:8001/accounts/` and `http://localhost:8002/orders/`
list existing accounts/orders and have a form to create one — each
creation redirects to a "dashboard" (`.../<pk>/dashboard/`) that shows
local data **and** the remotely resolved data side by side, with a form
to update the local value (triggering the event, hence invalidation on
the other service) and, on `service_auth`'s side, a form to pin an
order by its id (`accounts/views.py`, `orders/views.py`).

### Option A (recommended): everything in one command with Docker

```sh
docker compose -f example/docker-compose.yml up -d --build
```

A single image (`Dockerfile` at the repo root) is the base for seven
containers: Redis, a disposable `_migrate` container per service
(applies migrations then exits — the others wait for it to succeed to
avoid concurrent migrations on the same SQLite file), and each service's
`_http`/`_grpc`/`_worker` processes. Nothing to start by hand.
`docker compose -f example/docker-compose.yml ps` should show six
containers `Up` (the two `_migrate` ones exit, which is expected).

The simplest way: open `http://localhost:8001/accounts/` and
`http://localhost:8002/orders/` in a browser, create an account then an
order (referencing its id), and pin it from the account's dashboard —
everything happens through forms, no command to type.

Command-line alternative, via `docker compose exec` (a plain
`manage.py shell`, inside the container):

```sh
echo "
from django.contrib.auth.models import User
User.objects.create_user(username='bob', email='bob@example.com', password='x')
" | docker compose -f example/docker-compose.yml exec -T service_auth_http \
    uv run python example/service_auth/manage.py shell

echo "
from orders.models import Order
Order.objects.create(reference='ORD-1', user_id=1)
" | docker compose -f example/docker-compose.yml exec -T service_order_http \
    uv run python example/service_order/manage.py shell

echo "
from django.contrib.auth.models import User
from accounts.models import OrderBookmark
OrderBookmark.objects.create(user=User.objects.get(pk=1), order_id=1)
" | docker compose -f example/docker-compose.yml exec -T service_auth_http \
    uv run python example/service_auth/manage.py shell
```

Then check both dashboards:

```sh
curl http://localhost:8002/orders/1/dashboard/      # service_order -> service_auth direction
curl http://localhost:8001/accounts/1/dashboard/    # service_auth -> service_order direction
```

Each shows its local data plus the remotely resolved one. Update either
side (same `echo ... | docker compose exec ... manage.py shell` pattern,
`User.objects.get(pk=1).email = "..."; .save()` or
`Order.objects.get(pk=1).reference = "..."; .save()`) then reload both
`curl` calls: each dashboard reflects the up-to-date value, invalidated
by the event published by the other service — **without restarting any
container**.

To stop and clean up everything: `docker compose -f example/docker-compose.yml down -v`.

### Option B: by hand, step by step, to understand each piece

```sh
# Terminal 1: Redis
docker compose -f example/docker-compose.yml up -d redis

# Once, to create the sqlite databases
uv run python example/service_auth/manage.py migrate
uv run python example/service_order/manage.py migrate

# Terminal 2: service_auth answers over HTTP on :8001
uv run python example/service_auth/manage.py runserver 8001
# Terminal 3: service_auth also answers over gRPC on :50051
uv run python example/service_auth/manage.py remote_grpc_server --port 50051
# Terminal 4: service_auth consumes orders.order_updated
uv run python example/service_auth/manage.py eventbus_worker

# Terminal 5: service_order answers over HTTP on :8002
uv run python example/service_order/manage.py runserver 8002
# Terminal 6: service_order consumes auth.user_created/user_updated
uv run python example/service_order/manage.py eventbus_worker
```

**Step A — an event crosses the bus.** In a 7th terminal:

```
uv run python example/service_auth/manage.py shell
>>> from django.contrib.auth.models import User
>>> User.objects.create_user(username="bob", email="bob@example.com", password="x")
```

`service_auth` publishes `auth.user_created`; the worker in terminal 6
consumes it and persists a `ReceivedEvent`. `service_order` never
imported a single line of `service_auth`'s code for this to work.

**Step B — `RemoteForeignKey` resolves over HTTP, in both directions.**

```
uv run python example/service_order/manage.py shell
>>> from orders.models import Order
>>> order = Order.objects.create(reference="ORD-1", user_id=1)
>>> order.user.email
'bob@example.com'
```

```
uv run python example/service_auth/manage.py shell
>>> from django.contrib.auth.models import User
>>> from accounts.models import OrderBookmark
>>> OrderBookmark.objects.create(user=User.objects.get(pk=1), order_id=1)
```

Check both dashboards in a browser (or `curl`):
`http://localhost:8002/orders/1/dashboard/` and
`http://localhost:8001/accounts/1/dashboard/`.

**Step C — event-driven invalidation, in both directions.** Still in a
`service_auth` shell:

```
>>> u = User.objects.get(username="bob")
>>> u.email = "bob.new@example.com"
>>> u.save()
```

And in a `service_order` shell:

```
>>> order.reference = "ORD-1-v2"
>>> order.save()
```

Each `.save()` publishes an event (`auth.user_updated` /
`orders.order_updated`) that the *other* service's worker consumes to
invalidate its cache. **Reload both dashboards** (`curl` or browser,
without restarting any process): both now reflect the up-to-date values.

**Step D — the same `order.user` works over gRPC.** In the
`service_order` shell:

```
>>> from django.test import override_settings
>>> with override_settings(REMOTE_DATA={
...     "SERVICE_REGISTRY": {"service_auth": {"grpc": {"target": "localhost:50051"}}},
...     "DEFAULT_TRANSPORT": "grpc",
... }):
...     print(order.user.as_dict())
{'id': 1, 'username': 'bob', 'email': 'bob.new@example.com', 'full_name': 'bob'}
```

Same `@expose_resource` on `service_auth`'s side, different transport on
`service_order`'s side — that's all that had to change.

## Tests

```
uv run pytest                       # unit (LocMemBroker, FakeTransport, in-memory gRPC) — no infra
docker compose -f example/docker-compose.yml up -d redis
uv run pytest -m integration        # against a real Redis
uv run ruff check .                 # PEP 8 / PEP 257 (pydocstyle) / imports / naming
uv run ruff format --check src tests example
uv run mypy src                     # PEP 484/526 (static typing)
```

## Regenerating the gRPC stubs

After modifying `src/django_event_bus/remote/proto/remote_resource.proto`:

```
./scripts/generate_grpc_stubs.sh
```

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) to contribute and
[CHANGELOG.md](CHANGELOG.md) for the version history.

## License

[MIT](LICENSE)
