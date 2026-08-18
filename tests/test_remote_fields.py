import pytest
from django.core.cache import cache

from django_event_bus.exceptions import RemoteServiceUnavailableError
from django_event_bus.remote import RemoteObject
from django_event_bus.remote.fields import RemoteForeignKeyDescriptor
from tests.fakes import FakeTransport
from tests.testapp.models import Order, Ticket


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


def test_set_accepts_raw_pk():
    order = Order()

    order.user = 7

    assert order.user_id == 7


def test_default_accessor_suffix_when_field_name_has_no_id_suffix():
    """`assignee` (pas `assignee_id`) ne peut pas devenir l'accesseur
    sans écraser le champ de stockage: il devient `assignee_remote`."""
    assert isinstance(Ticket.assignee_remote, RemoteForeignKeyDescriptor)
    assert not isinstance(Ticket.assignee, RemoteForeignKeyDescriptor)


def test_explicit_accessor_name_overrides_default():
    assert isinstance(Ticket.owner_account, RemoteForeignKeyDescriptor)


@pytest.mark.django_db
def test_default_suffix_accessor_resolves_correctly():
    FakeTransport.data[("service_auth", "users", 5)] = {
        "id": 5,
        "email": "e@example.com",
    }
    ticket = Ticket.objects.create(assignee=5, owner_id=5)

    assert ticket.assignee_remote.email == "e@example.com"


@pytest.mark.django_db
def test_explicit_accessor_name_resolves_correctly():
    FakeTransport.data[("service_auth", "users", 6)] = {
        "id": 6,
        "email": "f@example.com",
    }
    ticket = Ticket.objects.create(assignee=6, owner_id=6)

    assert ticket.owner_account.email == "f@example.com"


@pytest.mark.django_db
def test_cache_is_isolated_per_pk():
    """Résoudre le PK 1 ne doit ni appeler ni mettre en cache le PK 2:
    chaque ressource distante a sa propre clé de cache."""
    FakeTransport.data[("service_auth", "users", 1)] = {
        "id": 1,
        "email": "one@example.com",
    }
    FakeTransport.data[("service_auth", "users", 2)] = {
        "id": 2,
        "email": "two@example.com",
    }
    order_1 = Order.objects.create(user_id=1)
    order_2 = Order.objects.create(user_id=2)

    assert order_1.user.email == "one@example.com"
    assert order_2.user.email == "two@example.com"
    assert sorted(FakeTransport.calls) == [
        ("service_auth", "users", 1),
        ("service_auth", "users", 2),
    ]

    # Les deux restent en cache indépendamment: aucun appel supplémentaire.
    assert order_1.user.email == "one@example.com"
    assert order_2.user.email == "two@example.com"
    assert len(FakeTransport.calls) == 2


def test_deconstruct_round_trips_field_kwargs():
    """`deconstruct()` doit permettre de reconstruire un champ
    équivalent — c'est ce que `makemigrations` fait à chaque exécution
    pour décider si le schéma a changé."""
    field = Order._meta.get_field("user_id")

    _name, path, args, kwargs = field.deconstruct()
    rebuilt_cls = __import__(path.rsplit(".", 1)[0], fromlist=[path.rsplit(".", 1)[1]])
    rebuilt_field_cls = getattr(rebuilt_cls, path.rsplit(".", 1)[1])
    rebuilt = rebuilt_field_cls(*args, **kwargs)

    assert rebuilt.service == field.service
    assert rebuilt.resource == field.resource
    assert rebuilt.invalidate_on == field.invalidate_on


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
