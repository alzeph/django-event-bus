import pytest

from django_event_bus import RemoteSignal
from django_event_bus.brokers.utils import get_broker
from django_event_bus.dispatcher import dispatch
from django_event_bus.registry import get_receivers
from tests.testapp import events as testapp_events


def test_events_module_autodiscovered_at_startup():
    # `tests/testapp/events.py` n'est importé nulle part explicitement:
    # sa présence dans le registre prouve que AppConfig.ready() a bien
    # exécuté autodiscover_modules("events") au démarrage de Django.
    assert testapp_events.on_autodiscovered in get_receivers("testapp.autodiscovered")


@pytest.mark.django_db(transaction=True)
# transaction=True: RemoteSignal.send() publie via transaction.on_commit(),
# voir tests/test_signals.py pour le détail.
def test_full_pipeline_through_autodiscovered_receiver():
    testapp_events.received.clear()
    broker = get_broker()
    consumer = broker.listen({"testapp.autodiscovered"})

    RemoteSignal("testapp.autodiscovered").send(payload={"x": 1})

    envelope = next(consumer)
    assert dispatch(broker, envelope) is True
    assert testapp_events.received == [{"x": 1}]
