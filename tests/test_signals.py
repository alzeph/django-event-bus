import pytest

from django_event_bus import RemoteSignal, receiver
from django_event_bus.brokers.locmem import LocMemBroker
from django_event_bus.brokers.utils import get_broker
from django_event_bus.dispatcher import dispatch
from django_event_bus.envelope import EventEnvelope
from django_event_bus.registry import register


@pytest.mark.django_db(transaction=True)
# transaction=True: RemoteSignal.send() publie via transaction.on_commit(),
# qui ne se déclenche jamais sous le rollback implicite du marqueur
# django_db par défaut (le test n'aurait alors aucune donnée committée).
def test_send_and_dispatch_delivers_to_receiver():
    received = []

    @receiver("orders.created")
    def handle(payload, envelope, **kwargs):
        received.append(payload)

    broker = get_broker()
    consumer = broker.listen({"orders.created"})

    RemoteSignal("orders.created").send(payload={"order_id": 42})

    envelope = next(consumer)
    assert envelope.payload == {"order_id": 42}
    assert envelope.event_type == "orders.created"
    assert envelope.source_service == "test_service"

    assert dispatch(broker, envelope) is True
    assert received == [{"order_id": 42}]


def test_dispatch_fails_when_handler_raises():
    def bad_handler(**kwargs):
        raise ValueError("boom")

    register("failing.event", bad_handler)
    broker = LocMemBroker(service_name="test_service", options={})
    envelope = EventEnvelope(
        event_type="failing.event", source_service="test_service", payload={}
    )

    assert dispatch(broker, envelope) is False


def test_dispatch_with_no_receiver_acks_without_error():
    broker = LocMemBroker(service_name="test_service", options={})
    envelope = EventEnvelope(
        event_type="nobody.listens", source_service="test_service", payload={}
    )

    assert dispatch(broker, envelope) is True
