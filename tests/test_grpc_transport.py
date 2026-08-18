from collections.abc import Iterator
from concurrent import futures

import grpc
import pytest

from django_event_bus.exceptions import RemoteServiceUnavailableError
from django_event_bus.remote.grpc_server import RemoteResourceServicer
from django_event_bus.remote.proto import remote_resource_pb2_grpc
from django_event_bus.remote.transports.grpc import GRPCTransport

# Doit correspondre à REMOTE_DATA["SERVICE_REGISTRY"]["service_auth"]["grpc"]["target"]
# dans tests/settings.py.
_PORT = 50999


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
