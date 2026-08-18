import pytest
import requests

from django_event_bus.exceptions import RemoteServiceUnavailableError
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
