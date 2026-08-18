import pytest

from django_event_bus.brokers.locmem import LocMemBroker
from django_event_bus.brokers.utils import reset_broker


@pytest.fixture(autouse=True)
def _reset_event_bus_runtime_state():
    yield
    LocMemBroker.reset()
    reset_broker()
