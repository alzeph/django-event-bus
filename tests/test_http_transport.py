import pytest
import requests
from django.test import override_settings

from django_event_bus.exceptions import (
    RemoteServiceMisconfiguredError,
    RemoteServiceUnavailableError,
)
from django_event_bus.remote.transports.http import HTTPTransport


def test_fetch_returns_json_body(requests_mock):
    requests_mock.get(
        "http://testserver/api/users/1/", json={"id": 1, "email": "a@example.com"}
    )
    transport = HTTPTransport()

    data = transport.fetch(service="service_auth", resource="users", pk=1)

    assert data == {"id": 1, "email": "a@example.com"}


def test_fetch_returns_none_on_404(requests_mock):
    requests_mock.get("http://testserver/api/users/999/", status_code=404)
    transport = HTTPTransport()

    assert transport.fetch(service="service_auth", resource="users", pk=999) is None


def test_fetch_raises_on_server_error(requests_mock):
    requests_mock.get("http://testserver/api/users/1/", status_code=500)
    transport = HTTPTransport()

    with pytest.raises(RemoteServiceUnavailableError):
        transport.fetch(service="service_auth", resource="users", pk=1)


def test_fetch_raises_on_connection_error(requests_mock):
    requests_mock.get("http://testserver/api/users/1/", exc=requests.ConnectionError)
    transport = HTTPTransport()

    with pytest.raises(RemoteServiceUnavailableError):
        transport.fetch(service="service_auth", resource="users", pk=1)


def test_fetch_sends_configured_headers(requests_mock):
    """Les en-têtes déclarés dans SERVICE_REGISTRY (ex: un token de
    service-à-service) sont bien transmis à chaque requête."""
    requests_mock.get("http://testserver/api/users/1/", json={"id": 1})
    registry = {
        "service_auth": {
            "http": {
                "base_url": "http://testserver/api",
                "timeout": 3,
                "headers": {"Authorization": "Bearer test-token"},
            }
        }
    }

    with override_settings(REMOTE_DATA={"SERVICE_REGISTRY": registry}):
        transport = HTTPTransport()
        transport.fetch(service="service_auth", resource="users", pk=1)

    assert requests_mock.last_request.headers["Authorization"] == "Bearer test-token"


def test_fetch_sends_auth_token_as_bearer_header(requests_mock):
    """``auth_token`` est un raccourci pour ne pas reconstruire soi-même
    l'en-tête Authorization via ``headers``."""
    requests_mock.get("http://testserver/api/users/1/", json={"id": 1})
    registry = {
        "service_auth": {
            "http": {
                "base_url": "http://testserver/api",
                "timeout": 3,
                "auth_token": "s3cr3t",
            }
        }
    }

    with override_settings(REMOTE_DATA={"SERVICE_REGISTRY": registry}):
        transport = HTTPTransport()
        transport.fetch(service="service_auth", resource="users", pk=1)

    assert requests_mock.last_request.headers["Authorization"] == "Bearer s3cr3t"


def test_fetch_raises_on_invalid_json_body(requests_mock):
    requests_mock.get(
        "http://testserver/api/users/1/",
        text="<html>not json</html>",
        status_code=200,
    )
    transport = HTTPTransport()

    with pytest.raises(RemoteServiceUnavailableError):
        transport.fetch(service="service_auth", resource="users", pk=1)


def test_fetch_raises_when_response_exceeds_max_response_bytes(requests_mock):
    requests_mock.get(
        "http://testserver/api/users/1/", json={"id": 1, "padding": "x" * 1000}
    )
    registry = {
        "service_auth": {"http": {"base_url": "http://testserver/api", "timeout": 3}}
    }

    with override_settings(
        REMOTE_DATA={"MAX_RESPONSE_BYTES": 10, "SERVICE_REGISTRY": registry}
    ):
        transport = HTTPTransport()
        with pytest.raises(RemoteServiceUnavailableError, match="taille"):
            transport.fetch(service="service_auth", resource="users", pk=1)


def test_fetch_respects_per_service_max_response_bytes_override(requests_mock):
    requests_mock.get(
        "http://testserver/api/users/1/", json={"id": 1, "padding": "x" * 1000}
    )
    registry = {
        "service_auth": {
            "http": {
                "base_url": "http://testserver/api",
                "timeout": 3,
                "max_response_bytes": 10,
            }
        }
    }

    with override_settings(REMOTE_DATA={"SERVICE_REGISTRY": registry}):
        transport = HTTPTransport()
        with pytest.raises(RemoteServiceUnavailableError):
            transport.fetch(service="service_auth", resource="users", pk=1)


def test_fetch_raises_when_require_tls_and_base_url_is_not_https(requests_mock):
    registry = {
        "service_auth": {"http": {"base_url": "http://testserver/api", "timeout": 3}}
    }

    with override_settings(
        REMOTE_DATA={"REQUIRE_TLS": True, "SERVICE_REGISTRY": registry}
    ):
        transport = HTTPTransport()
        with pytest.raises(RemoteServiceMisconfiguredError, match="REQUIRE_TLS"):
            transport.fetch(service="service_auth", resource="users", pk=1)
