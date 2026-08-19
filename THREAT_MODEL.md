# Threat model

English · [Français](THREAT_MODEL.fr.md)

`django-event-bus` is a library, not a deployed service: it runs inside
each adopting service's own process and trust boundary. This document
describes the assets it touches, the actors considered, and which risks
are mitigated in code versus accepted by design (and why) — the
reasoning behind the points already listed in
[SECURITY.md](SECURITY.md), not a duplicate of them.

## Scope

In scope: the library's own code (`src/django_event_bus/`) — the event
bus (Redis Streams broker, dispatcher), and the remote-data layer
(`RemoteForeignKey`, `@expose_resource`, the HTTP/gRPC transports and
servers).

Out of scope: the security of Redis, the Django application embedding
the library, the network/mesh the services run on, and the `example/`
demo (intentionally insecure defaults for local use — see its own
`DEBUG = True`, `SECRET_KEY` in plaintext).

## Assets

- **Event payloads** in transit (Redis Streams) and at rest (until
  consumed/trimmed): arbitrary JSON supplied by the adopting service,
  potentially containing business data.
- **Exposed resource data**: whatever a `ResourceSerializer` puts in its
  `fields` — the library does not know which columns are sensitive.
- **Shared secrets / signing keys**: `AUTH_TOKEN`, a `JWTAuthBackend`
  signing key, TLS private keys — supplied by the adopting service,
  never generated or stored by the library itself.
- **Service availability**: the event bus worker, the gRPC/HTTP
  endpoints, the Redis connection.

## Actors

| Actor | Assumed capability |
|---|---|
| Another service in `SERVICE_REGISTRY` | Trusted by default (see "Accepted risks" below): can reach the configured transports, is expected to run code from the same organization. |
| An operator with Redis access | Can read/write any stream, including dead-letter — sees event payloads in plaintext. |
| A network-adjacent attacker (same VPC/segment, no valid credentials) | Can attempt to reach `resource_detail`/the gRPC port if network isolation is misconfigured. The primary actor the auth/TLS/rate-limit options in `SECURITY.md` defend against. |
| A caller holding a leaked static `AUTH_TOKEN` | Gains the same access as any legitimate consumer of that service's exposed resources — the static-token backend cannot distinguish them (see "Accepted risks"). |

## STRIDE, by component

| Component | Threat | Mitigation | Residual risk |
|---|---|---|---|
| `resource_detail` / gRPC `GetResource` | **Spoofing** — caller impersonation | `AUTH_BACKEND`/`AUTH_TOKEN` (optional), TLS (optional, `REQUIRE_TLS` to enforce) | Both are opt-in; a misconfigured deployment is unauthenticated by design (documented trust-in-network assumption) |
| `resource_detail` / gRPC `GetResource` | **Tampering** — altered request in transit | TLS (optional) | Plaintext transport if TLS not configured |
| Redis Streams | **Tampering** — an operator or a compromised process rewrites stream entries | None (Redis' own ACLs/auth are the adopting service's responsibility) | Out of scope — Redis hardening is the deployer's job |
| `resource_detail` / gRPC `GetResource` | **Repudiation** — no record of who accessed what | `remote.audit` structured logger (granted/denied, caller, peer, resource, pk) | Log storage/retention is the deployer's responsibility; the static-token backend cannot attribute a granted access to an individual caller |
| `ResourceSerializer` / `@expose_resource` | **Information disclosure** — a sensitive field ends up in `fields` | None automatic — `SECURITY.md` documents the review responsibility | Library cannot know which columns are sensitive; a "deny-by-default" allowlist (`fields`, not `"__all__"`) is a convention, not enforced |
| HTTP/gRPC transports (consumer side) | **Information disclosure / DoS** — oversized response from a compromised "trusted" peer | `MAX_RESPONSE_BYTES` (bounded read, chunked) | A peer within the byte limit can still return misleading (but well-formed) data — trust in the peer's data, not just its size, is still assumed |
| `resource_detail` / gRPC `GetResource` | **Denial of service** — request flood | `RATE_LIMIT` (on by default, coarse fixed window, cache-backed) | A distributed flood (many source addresses/peers) is not mitigated; this is abuse protection, not DDoS protection |
| Dispatcher / receivers | **Elevation of privilege** — a receiver granted more trust than the event warrants | None — receivers run with the full privileges of the consuming service's process | By design: the event bus is an internal pub/sub within one trust domain, not a sandboxed plugin system |

## Accepted risks (by design)

These are not gaps to silently fix — they are documented trade-offs.
Reported as vulnerabilities, they will be triaged as "expected behavior,
documentation clarified" rather than "bug", unless the report shows a
way to defeat a stated mitigation (e.g. bypassing `RATE_LIMIT`, forging
a JWT without the key, reading a stream entry past `MAXLEN` retention
guarantees).

1. **Trust between registered services.** `SERVICE_REGISTRY` entries are
   assumed to be other services from the same organization/deployment.
   The library has no concept of "semi-trusted" or per-resource
   authorization between services — see `AUTH_BACKEND` for the closest
   approximation (a shared secret or a signed token), not true
   least-privilege RBAC.
2. **No encryption at rest.** Event payloads sit in Redis Streams (and
   the Django cache, for resolved `RemoteObject`s) as plaintext JSON.
   Encrypting them is the deployer's responsibility (Redis TLS,
   disk/volume encryption) if the payloads warrant it.
3. **At-least-once delivery, not exactly-once.** A receiver can run more
   than once for the same event (retry after a partial failure, a
   reclaimed pending message, ...). Receivers must be idempotent — this
   is a correctness contract, documented in the README, not a security
   boundary, but an attacker able to trigger repeated delivery of a
   legitimate event could exploit a non-idempotent receiver.
4. **The static-token auth backend is a shared secret, not an
   identity.** Anyone holding it is indistinguishable from any other
   legitimate holder in the audit log (`caller="shared-token"`). Use
   `JWTAuthBackend` when per-caller attribution matters.

## Out of scope for this library

- Redis authentication/ACLs/TLS configuration.
- The adopting Django service's own attack surface (its views, its
  `SECRET_KEY`, its `DEBUG` setting, ...).
- Physical/host-level security of wherever the services run.
- Supply-chain integrity of dependencies below `django-event-bus`
  itself (covered operationally by `pip-audit` in CI and Dependabot, not
  by this document).
