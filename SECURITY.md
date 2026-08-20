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

## Triage SLA

Once a report is confirmed as a genuine vulnerability, response and fix
targets depend on severity (roughly CVSS-aligned):

| Severity | Example | Initial response | Fix or mitigation published |
|---|---|---|---|
| Critical | Unauthenticated remote code execution, mass data exfiltration across services | 24h | 72h |
| High | Auth bypass on `resource_detail`/gRPC, cross-tenant data leak (see below) | 2 business days | 7 days |
| Medium | Privilege confusion under a specific configuration, DoS requiring elevated access | 5 business days | 30 days |
| Low | Hardening suggestion, defense-in-depth gap with no direct exploit path | Best effort | Next minor release |

These are targets, not contractual commitments — this is a single-
maintainer open-source project. A fix may ship as a patch release, or as
documented mitigation guidance when a code fix isn't the right answer
(e.g. "put this behind your VPN", already the case for several points
below).

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
  - **Authentication, pluggable**: `django_event_bus.remote.auth` defines
    `BaseAuthBackend`; the provider service selects one via
    `REMOTE_DATA["AUTH_BACKEND"]` (dotted path to an instance) or the
    `REMOTE_DATA["AUTH_TOKEN"]` shorthand. Two built-in backends:
    - `StaticTokenAuthBackend` (what `AUTH_TOKEN` builds): one shared
      secret for every caller, `Authorization: Bearer <token>`,
      constant-time comparison. No per-caller identity, no expiry — the
      secret must be rotated manually, and a leak grants access to
      everything the service exposes.
    - `JWTAuthBackend` (needs `pip install django-event-bus[jwt]`):
      verifies a signed, short-lived JWT (`exp` is mandatory) per caller,
      exposing the token's `sub` (or `iss`) as the caller identity for
      the audit log. Prefer this over a static token when callers should
      be distinguishable and secrets should expire on their own.
    On the consumer side, HTTP reads `auth_token` from
    `SERVICE_REGISTRY[service]["http"]` and gRPC from
    `SERVICE_REGISTRY[service]["grpc"]`; both attach the header/metadata
    automatically. Either backend is one layer on top of network
    isolation, not a replacement for it.
  - **TLS, and an option to require it**: `remote.grpc_server.serve()`
    accepts a `credentials` argument (`grpc.ServerCredentials`, e.g. from
    `grpc.ssl_server_credentials(...)`) to serve over TLS instead of
    `add_insecure_port`; wire it from `manage.py remote_grpc_server` via
    `REMOTE_DATA["GRPC_SERVER_CREDENTIALS"]` (dotted path to a
    zero-argument callable building it, e.g. from cert/key files or a
    secrets manager — kept out of the library so it isn't tied to one way
    of storing certificates). On the consumer side, set `credentials`
    (a `grpc.ChannelCredentials`) in `SERVICE_REGISTRY[service]["grpc"]`.
    The HTTP transport already goes over TLS whenever `base_url` is
    `https://`, standard `requests` behavior. Set
    `REMOTE_DATA["REQUIRE_TLS"] = True` to fail closed instead of
    silently falling back to plaintext: the HTTP transport then refuses
    a non-`https://` `base_url`, the gRPC transport refuses a service
    without `credentials`, and `manage.py remote_grpc_server` refuses to
    start without `GRPC_SERVER_CREDENTIALS`.
  - **Rate limiting, on by default**: `REMOTE_DATA["RATE_LIMIT"]`
    (default `{"LIMIT": 300, "WINDOW_SECONDS": 60}`, `None` disables it)
    throttles `resource_detail` by the caller's `REMOTE_ADDR` and the
    generic gRPC server by peer address, using the same Django cache as
    cached remote data — a coarse fixed window, sufficient against abuse
    and credential-guessing sprees, not a precise rate guarantee. For
    anything more specific, `serve()`'s `interceptors` sequence still
    accepts your own `grpc.ServerInterceptor`, applied after the built-in
    rate limiter and auth check.
  - **Response size limits**: `REMOTE_DATA["MAX_RESPONSE_BYTES"]`
    (default 2 MB) bounds how much of a remote HTTP/gRPC response the
    consumer transports will read before giving up
    (`RemoteServiceUnavailableError`) — protects a consumer against a
    compromised or misconfigured "trusted" peer returning an oversized
    body. Overridable per service via
    `SERVICE_REGISTRY[service]["http"|"grpc"]["max_response_bytes"]`.
  - **Audit trail**: every access decision (granted or denied) on
    `resource_detail` and the generic gRPC server is logged via the
    `django_event_bus.remote.audit` logger (structured `extra` fields:
    transport, resource, pk, caller, peer, granted, reason) — route or
    filter it independently of application logs.
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

See [THREAT_MODEL.md](THREAT_MODEL.md) for the fuller picture: trust
boundaries, the assets and attackers considered, and which risks are
accepted by design rather than mitigated in code.
