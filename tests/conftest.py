import pytest
from django.core.cache import cache

from django_event_bus.brokers.locmem import LocMemBroker
from django_event_bus.brokers.utils import reset_broker


@pytest.fixture(autouse=True)
def _reset_event_bus_runtime_state():
    yield
    LocMemBroker.reset()
    reset_broker()
    # Le cache par défaut (locmem, process-wide) est partagé par les
    # données distantes mises en cache ET par le rate limiter: sans ce
    # nettoyage, un test qui approche une fenêtre de rate limit
    # laisserait un compteur en place pour le test suivant.
    #
    # The default cache (locmem, process-wide) is shared by cached
    # remote data AND by the rate limiter: without this cleanup, a test
    # nearing a rate-limit window would leave a counter in place for the
    # next test.
    cache.clear()
