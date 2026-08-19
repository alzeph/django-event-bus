# Security policy

English · [Français](SECURITY.fr.md)

## Reporting a vulnerability

Please don't open a public issue for a security vulnerability. Instead,
contact the maintainer directly at
[hervecedricyouan@gmail.com](mailto:hervecedricyouan@gmail.com) with:

- a description of the problem and its impact;
- reproduction steps;
- the affected `django-event-bus` version.

A response is targeted within 5 business days.

## Points of attention specific to an inter-service event bus

`django-event-bus` moves data and triggers code across service and
network boundaries. A few points deserve particular attention:

- **`RemoteForeignKey` and `@expose_resource`** assume the configured
  transports (HTTP, gRPC) reach *trusted* services on a private/internal
  network. By default, neither the generic HTTP view
  (`django_event_bus.remote.views.resource_detail`) nor the generic gRPC
  server (`django_event_bus.remote.grpc_server`) perform authentication
  or authorization — they answer any caller that can reach them. Put them
  behind your own network boundary (VPC, service mesh, reverse proxy with
  auth) rather than exposing them publicly.
  - **Optional shared-secret auth**: set `REMOTE_DATA["AUTH_TOKEN"]` on
    the provider service to require every HTTP/gRPC call to present
    `Authorization: Bearer <AUTH_TOKEN>` (constant-time comparison; HTTP
    gets a 401, gRPC an `UNAUTHENTICATED` status otherwise). On the
    consumer side, set `auth_token` in the matching
    `SERVICE_REGISTRY[service]["http"|"grpc"]` entry and both transports
    attach it automatically. This is a shared secret, not per-caller
    identity or fine-grained authorization — suitable as one layer on top
    of network isolation, not a replacement for it.
  - **TLS for gRPC**: `remote.grpc_server.serve()` accepts a `credentials`
    argument (`grpc.ServerCredentials`, e.g. from
    `grpc.ssl_server_credentials(...)`) to serve over TLS instead of
    `add_insecure_port`; wire it from `manage.py remote_grpc_server` via
    `REMOTE_DATA["GRPC_SERVER_CREDENTIALS"]` (dotted path to a
    zero-argument callable building it, e.g. from cert/key files or a
    secrets manager — kept out of the library so it isn't tied to one way
    of storing certificates). On the consumer side, set `credentials`
    (a `grpc.ChannelCredentials`) in `SERVICE_REGISTRY[service]["grpc"]`.
    The HTTP transport already goes over TLS whenever `base_url` is
    `https://`, standard `requests` behavior.
  - **Rate limiting**: not built in, to avoid forcing a specific
    dependency. For HTTP, wrap `resource_detail` yourself in your own
    `urls.py` (e.g. with `django-ratelimit`) instead of including
    `django_event_bus.remote.urls` as-is. For gRPC, `serve()` accepts an
    `interceptors` sequence — pass your own `grpc.ServerInterceptor` for
    rate limiting; it runs after the `auth_token` check, if configured.
- **`ResourceSerializer`** only exposes the fields you explicitly list
  (`fields`) or don't exclude (`exclude`); a resource declared with
  `fields = "__all__"` on a model holding sensitive columns (password
  hashes, tokens, ...) will serialize them. Review `Meta.fields`/
  `Meta.exclude` on any model that isn't a pure DTO.
- **Event payloads** (`RemoteSignal.send(payload=...)`) are serialized
  as JSON and stored in Redis Streams (or kept in the process for
  `LocMemBroker`). Don't put secrets or full sensitive records in a
  payload; a receiver in another service, or an operator inspecting the
  stream, will see it in plaintext.
- **gRPC payloads** are carried as JSON strings rather than
  `google.protobuf.Struct` (see the README) specifically to preserve
  numeric precision — this has no security implication of its own, but
  means a malformed or oversized JSON payload from an untrusted gRPC
  peer is parsed with the standard library's `json` module; keep gRPC
  endpoints reachable only from trusted services, as noted above.
- A bug causing a receiver, a resolved `RemoteForeignKey`, or an exposed
  resource to leak data across the wrong service or the wrong tenant is
  a high-severity vulnerability and should be reported as such, not as
  a regular feature bug.
