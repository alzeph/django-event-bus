import pytest
from django.core.cache import cache

from django_event_bus import RemoteSignal
from django_event_bus.brokers.utils import get_broker
from django_event_bus.dispatcher import dispatch
from tests.fakes import FakeTransport
from tests.testapp.models import Order


@pytest.fixture(autouse=True)
def _reset_state():
    FakeTransport.reset()
    cache.clear()
    yield
    FakeTransport.reset()
    cache.clear()


@pytest.mark.django_db(transaction=True)
# transaction=True: RemoteSignal.send() publie via transaction.on_commit(),
# voir tests/test_signals.py pour le détail.
def test_cache_invalidated_on_bus_event():
    FakeTransport.data[("service_auth", "users", 1)] = {
        "id": 1,
        "email": "old@example.com",
    }
    order = Order.objects.create(user_id=1)

    assert order.user.email == "old@example.com"
    assert order.user.email == "old@example.com"  # cache chaud, pas de second appel
    assert len(FakeTransport.calls) == 1

    FakeTransport.data[("service_auth", "users", 1)] = {
        "id": 1,
        "email": "new@example.com",
    }

    broker = get_broker()
    consumer = broker.listen({"auth.user_updated"})
    RemoteSignal("auth.user_updated").send(payload={"id": 1})
    envelope = next(consumer)
    assert dispatch(broker, envelope) is True

    assert order.user.email == "new@example.com"
    assert len(FakeTransport.calls) == 2


@pytest.mark.django_db(transaction=True)
def test_invalidation_event_without_id_is_ignored(caplog):
    """Un événement d'invalidation dont le payload n'a pas de clé "id"
    (bug côté service source, événement mal formé) ne doit ni planter le
    worker ni invalider le cache au hasard: il est juste journalisé."""
    FakeTransport.data[("service_auth", "users", 1)] = {
        "id": 1,
        "email": "still-cached@example.com",
    }
    order = Order.objects.create(user_id=1)
    assert order.user.email == "still-cached@example.com"
    assert len(FakeTransport.calls) == 1

    broker = get_broker()
    consumer = broker.listen({"auth.user_updated"})
    RemoteSignal("auth.user_updated").send(payload={"note": "pas d'id ici"})
    envelope = next(consumer)

    with caplog.at_level("WARNING"):
        assert dispatch(broker, envelope) is True

    assert "sans 'id'" in caplog.text
    # Cache toujours chaud: aucune invalidation n'a eu lieu.
    assert order.user.email == "still-cached@example.com"
    assert len(FakeTransport.calls) == 1
