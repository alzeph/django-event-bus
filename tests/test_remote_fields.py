import pytest
from django.core.cache import cache

from django_event_bus.exceptions import RemoteServiceUnavailableError
from django_event_bus.remote import RemoteObject
from django_event_bus.remote.fields import RemoteForeignKeyDescriptor
from tests.fakes import FakeTransport
from tests.testapp.models import Order


@pytest.fixture(autouse=True)
def _reset_state():
    FakeTransport.reset()
    cache.clear()
    yield
    FakeTransport.reset()
    cache.clear()


def test_class_level_access_returns_descriptor():
    assert isinstance(Order.user, RemoteForeignKeyDescriptor)


def test_none_pk_returns_none_without_calling_transport():
    order = Order(user_id=None)

    assert order.user is None
    assert FakeTransport.calls == []


def test_set_accepts_remote_object():
    order = Order()
    remote_user = RemoteObject(
        service="service_auth", resource="users", pk=42, data={"id": 42}
    )

    order.user = remote_user

    assert order.user_id == 42


@pytest.mark.django_db
def test_resolves_via_transport_on_cache_miss():
    FakeTransport.data[("service_auth", "users", 1)] = {
        "id": 1,
        "email": "a@example.com",
    }
    order = Order.objects.create(user_id=1)

    user = order.user

    assert isinstance(user, RemoteObject)
    assert user.email == "a@example.com"
    assert FakeTransport.calls == [("service_auth", "users", 1)]


@pytest.mark.django_db
def test_second_access_hits_cache_not_transport():
    FakeTransport.data[("service_auth", "users", 1)] = {
        "id": 1,
        "email": "a@example.com",
    }
    order = Order.objects.create(user_id=1)

    _ = order.user
    _ = order.user

    assert FakeTransport.calls == [("service_auth", "users", 1)]


@pytest.mark.django_db
def test_returns_none_when_resource_not_found():
    order = Order.objects.create(user_id=999)

    assert order.user is None


@pytest.mark.django_db
def test_propagates_transport_error():
    FakeTransport.fail_on.add(("service_auth", "users", 1))
    order = Order.objects.create(user_id=1)

    with pytest.raises(RemoteServiceUnavailableError):
        _ = order.user
