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
