"""Tests du câblage TLS/auth/interceptors de ``remote.grpc_server.serve``.

``serve()`` bloque normalement sur ``stop_event.wait()``: ces tests
neutralisent le blocage et les handlers de signal (main thread requis,
sans intérêt ici) pour n'observer que la configuration du serveur gRPC
avant son démarrage.
"""

from __future__ import annotations

import signal
import threading

import grpc
import pytest

from django_event_bus.remote.auth import StaticTokenAuthBackend
from django_event_bus.remote.grpc_server import (
    _AuthInterceptor,
    _RateLimitInterceptor,
    serve,
)
from django_event_bus.remote.ratelimit import RateLimitConfig


class _FakeServer:
    def __init__(self) -> None:
        self.secure_port_calls: list[tuple[str, object]] = []
        self.insecure_port_calls: list[str] = []
        self.started = False

    def add_generic_rpc_handlers(self, handlers: object) -> None:
        pass

    def add_registered_method_handlers(
        self, service_name: str, method_handlers: object
    ) -> None:
        pass

    def add_secure_port(self, address: str, credentials: object) -> None:
        self.secure_port_calls.append((address, credentials))

    def add_insecure_port(self, address: str) -> None:
        self.insecure_port_calls.append(address)

    def start(self) -> None:
        self.started = True

    def stop(self, grace: float | None = None) -> _FakeFuture:
        return _FakeFuture()


class _FakeFuture:
    def wait(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _neutralize_blocking_calls(monkeypatch):
    """Empêche ``serve()`` de bloquer/d'installer de vrais handlers de signal."""
    monkeypatch.setattr(signal, "signal", lambda *args, **kwargs: None)
    monkeypatch.setattr(threading.Event, "wait", lambda self, timeout=None: None)


@pytest.fixture
def fake_server(monkeypatch) -> _FakeServer:
    server = _FakeServer()
    captured_interceptors: list = []
    captured_options: list = []

    def fake_grpc_server(executor, interceptors=None, options=None):
        captured_interceptors.extend(interceptors or [])
        captured_options.append(options)
        return server

    monkeypatch.setattr(grpc, "server", fake_grpc_server)
    server.captured_interceptors = captured_interceptors  # type: ignore[attr-defined]
    server.captured_options = captured_options  # type: ignore[attr-defined]
    return server


def _resolve(resource: str, pk: str) -> None:
    return None


def test_serve_defaults_to_insecure_port(fake_server):
    serve(_resolve, port=1234)

    assert fake_server.insecure_port_calls == ["[::]:1234"]
    assert fake_server.secure_port_calls == []


def test_serve_uses_secure_port_when_credentials_given(fake_server):
    sentinel_credentials = object()

    serve(_resolve, port=1234, credentials=sentinel_credentials)

    assert fake_server.secure_port_calls == [("[::]:1234", sentinel_credentials)]
    assert fake_server.insecure_port_calls == []


def test_serve_adds_no_interceptor_without_auth_token(fake_server):
    serve(_resolve)

    assert fake_server.captured_interceptors == []  # type: ignore[attr-defined]


def test_serve_adds_token_auth_interceptor_first(fake_server):
    extra_interceptor = object()

    serve(_resolve, auth_token="s3cr3t", interceptors=[extra_interceptor])

    interceptors = fake_server.captured_interceptors  # type: ignore[attr-defined]
    assert len(interceptors) == 2
    assert isinstance(interceptors[0], _AuthInterceptor)
    assert interceptors[1] is extra_interceptor


def test_serve_auth_backend_takes_precedence_over_auth_token(fake_server):
    backend = StaticTokenAuthBackend("from-backend")

    serve(_resolve, auth_token="ignored", auth_backend=backend)

    interceptors = fake_server.captured_interceptors  # type: ignore[attr-defined]
    assert len(interceptors) == 1
    assert interceptors[0]._backend is backend


def test_serve_adds_rate_limit_interceptor_before_auth(fake_server):
    rate_limit = RateLimitConfig(limit=10, window_seconds=60)

    serve(_resolve, rate_limit=rate_limit, auth_token="s3cr3t")

    interceptors = fake_server.captured_interceptors  # type: ignore[attr-defined]
    assert len(interceptors) == 2
    assert isinstance(interceptors[0], _RateLimitInterceptor)
    assert isinstance(interceptors[1], _AuthInterceptor)


def test_serve_passes_max_message_bytes_as_server_options(fake_server):
    serve(_resolve, max_message_bytes=123)

    options = fake_server.captured_options[0]  # type: ignore[attr-defined]
    assert ("grpc.max_receive_message_length", 123) in options
    assert ("grpc.max_send_message_length", 123) in options


def test_serve_omits_options_by_default(fake_server):
    serve(_resolve)

    assert fake_server.captured_options == [None]  # type: ignore[attr-defined]
