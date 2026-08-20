from collections.abc import Iterator
from concurrent import futures

import grpc
import pytest
from django.test import override_settings

from django_event_bus.exceptions import (
    RemoteServiceMisconfiguredError,
    RemoteServiceUnavailableError,
)
from django_event_bus.remote.auth import StaticTokenAuthBackend
from django_event_bus.remote.grpc_server import (
    RemoteResourceServicer,
    _AuthInterceptor,
    _RateLimitInterceptor,
)
from django_event_bus.remote.proto import remote_resource_pb2_grpc
from django_event_bus.remote.ratelimit import RateLimitConfig
from django_event_bus.remote.transports.grpc import GRPCTransport

# Doit correspondre à REMOTE_DATA["SERVICE_REGISTRY"]["service_auth"]["grpc"]["target"]
# dans tests/settings.py.
_PORT = 50999
_AUTH_PORT = 50998
_RATE_LIMIT_PORT = 50997


@pytest.fixture
def grpc_users() -> Iterator[dict[tuple[str, str], dict]]:
    data: dict[tuple[str, str], dict] = {
        ("users", "1"): {"id": 1, "email": "a@example.com"}
    }

    def resolve(resource: str, pk: str) -> dict | None:
        return data.get((resource, pk))

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    remote_resource_pb2_grpc.add_RemoteResourceServiceServicer_to_server(
        RemoteResourceServicer(resolve), server
    )
    server.add_insecure_port(f"[::]:{_PORT}")
    server.start()
    try:
        yield data
    finally:
        server.stop(grace=None)


def test_fetch_returns_dict(grpc_users):
    transport = GRPCTransport()
    try:
        result = transport.fetch(service="service_auth", resource="users", pk=1)
    finally:
        transport.close()

    assert result == {"id": 1, "email": "a@example.com"}


def test_fetch_returns_none_when_not_found(grpc_users):
    transport = GRPCTransport()
    try:
        result = transport.fetch(service="service_auth", resource="users", pk=999)
    finally:
        transport.close()

    assert result is None


def test_fetch_raises_when_server_unreachable():
    transport = GRPCTransport()
    try:
        with pytest.raises(RemoteServiceUnavailableError):
            transport.fetch(service="service_auth", resource="users", pk=1)
    finally:
        transport.close()


def test_channel_is_reused_across_multiple_fetches(grpc_users):
    """Le canal gRPC est ouvert une fois par service puis réutilisé, pas
    recréé à chaque fetch() — coûteux sinon (poignée de main TLS/TCP)."""
    transport = GRPCTransport()
    try:
        transport.fetch(service="service_auth", resource="users", pk=1)
        transport.fetch(service="service_auth", resource="users", pk=1)
        transport.fetch(service="service_auth", resource="users", pk=999)

        assert len(transport._channels) == 1
        assert "service_auth" in transport._channels
    finally:
        transport.close()

    assert transport._channels == {}


def test_channel_uses_secure_channel_when_credentials_configured(monkeypatch):
    """``config["credentials"]`` doit ouvrir un canal chiffré, pas en clair."""
    calls = []

    def fake_secure_channel(target, credentials, options=None):
        calls.append((target, credentials))
        return object()

    monkeypatch.setattr(grpc, "secure_channel", fake_secure_channel)
    sentinel_credentials = object()
    transport = GRPCTransport()

    transport._channel(
        "service_auth", {"target": "localhost:1", "credentials": sentinel_credentials}
    )

    assert calls == [("localhost:1", sentinel_credentials)]


def test_channel_passes_max_response_bytes_as_message_length_option(monkeypatch):
    calls = []

    def fake_insecure_channel(target, options=None):
        calls.append(options)
        return object()

    monkeypatch.setattr(grpc, "insecure_channel", fake_insecure_channel)
    transport = GRPCTransport()

    transport._channel(
        "service_auth", {"target": "localhost:1", "max_response_bytes": 42}
    )

    assert calls == [[("grpc.max_receive_message_length", 42)]]


def test_fetch_raises_when_require_tls_and_no_credentials_configured():
    registry = {"service_auth": {"grpc": {"target": "localhost:50999", "timeout": 3}}}

    with override_settings(
        REMOTE_DATA={"REQUIRE_TLS": True, "SERVICE_REGISTRY": registry}
    ):
        transport = GRPCTransport()
        try:
            with pytest.raises(RemoteServiceMisconfiguredError, match="REQUIRE_TLS"):
                transport.fetch(service="service_auth", resource="users", pk=1)
        finally:
            transport.close()


@pytest.fixture
def grpc_users_with_auth() -> Iterator[dict[tuple[str, str], dict]]:
    data: dict[tuple[str, str], dict] = {
        ("users", "1"): {"id": 1, "email": "a@example.com"}
    }

    def resolve(resource: str, pk: str) -> dict | None:
        return data.get((resource, pk))

    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=2),
        interceptors=[_AuthInterceptor(StaticTokenAuthBackend("s3cr3t"))],
    )
    remote_resource_pb2_grpc.add_RemoteResourceServiceServicer_to_server(
        RemoteResourceServicer(resolve), server
    )
    server.add_insecure_port(f"[::]:{_AUTH_PORT}")
    server.start()
    try:
        yield data
    finally:
        server.stop(grace=None)


def test_fetch_rejected_without_matching_auth_token(grpc_users_with_auth):
    registry = {
        "service_auth": {"grpc": {"target": f"localhost:{_AUTH_PORT}", "timeout": 3}}
    }

    with override_settings(REMOTE_DATA={"SERVICE_REGISTRY": registry}):
        transport = GRPCTransport()
        try:
            with pytest.raises(RemoteServiceUnavailableError):
                transport.fetch(service="service_auth", resource="users", pk=1)
        finally:
            transport.close()


def test_fetch_succeeds_with_matching_auth_token(grpc_users_with_auth):
    registry = {
        "service_auth": {
            "grpc": {
                "target": f"localhost:{_AUTH_PORT}",
                "timeout": 3,
                "auth_token": "s3cr3t",
            }
        }
    }

    with override_settings(REMOTE_DATA={"SERVICE_REGISTRY": registry}):
        transport = GRPCTransport()
        try:
            result = transport.fetch(service="service_auth", resource="users", pk=1)
        finally:
            transport.close()

    assert result == {"id": 1, "email": "a@example.com"}


@pytest.fixture
def grpc_users_with_rate_limit() -> Iterator[dict[tuple[str, str], dict]]:
    data: dict[tuple[str, str], dict] = {
        ("users", "1"): {"id": 1, "email": "a@example.com"}
    }

    def resolve(resource: str, pk: str) -> dict | None:
        return data.get((resource, pk))

    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=2),
        interceptors=[
            _RateLimitInterceptor(RateLimitConfig(limit=1, window_seconds=60))
        ],
    )
    remote_resource_pb2_grpc.add_RemoteResourceServiceServicer_to_server(
        RemoteResourceServicer(resolve), server
    )
    server.add_insecure_port(f"[::]:{_RATE_LIMIT_PORT}")
    server.start()
    try:
        yield data
    finally:
        server.stop(grace=None)


def test_fetch_rejected_once_rate_limit_exceeded(grpc_users_with_rate_limit):
    registry = {
        "service_auth": {
            "grpc": {"target": f"localhost:{_RATE_LIMIT_PORT}", "timeout": 3}
        }
    }

    with override_settings(REMOTE_DATA={"SERVICE_REGISTRY": registry}):
        transport = GRPCTransport()
        try:
            first = transport.fetch(service="service_auth", resource="users", pk=1)
            assert first == {"id": 1, "email": "a@example.com"}

            with pytest.raises(RemoteServiceUnavailableError):
                transport.fetch(service="service_auth", resource="users", pk=1)
        finally:
            transport.close()


def test_fetch_reflects_data_updated_between_calls(grpc_users):
    """Le transport ne met rien en cache lui-même: deux fetch()
    successifs reflètent l'état courant côté serveur, sans délai."""
    transport = GRPCTransport()
    try:
        first = transport.fetch(service="service_auth", resource="users", pk=1)
        assert first == {"id": 1, "email": "a@example.com"}

        grpc_users[("users", "1")] = {"id": 1, "email": "updated@example.com"}

        second = transport.fetch(service="service_auth", resource="users", pk=1)
        assert second == {"id": 1, "email": "updated@example.com"}
    finally:
        transport.close()
