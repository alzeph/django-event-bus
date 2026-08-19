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
  network. Neither the generic HTTP view
  (`django_event_bus.remote.views.resource_detail`) nor the generic gRPC
  server (`django_event_bus.remote.grpc_server`) perform authentication
  or authorization by default — they answer any caller that can reach
  them. Put them behind your own network boundary (VPC, service mesh,
  reverse proxy with auth) rather than exposing them publicly.
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
