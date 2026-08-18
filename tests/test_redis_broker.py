import time

import pytest
import redis as redis_lib

from django_event_bus.brokers.redis_streams import RedisStreamsBroker
from django_event_bus.dispatcher import dispatch
from django_event_bus.envelope import EventEnvelope
from django_event_bus.registry import register

REDIS_URL = "redis://localhost:6379/0"


def _redis_available() -> bool:
    try:
        return redis_lib.Redis.from_url(REDIS_URL).ping()
    except Exception:  # noqa: BLE001 - simple probe, toute erreur => indisponible
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _redis_available(), reason="Redis indisponible sur localhost:6379"
    ),
]


def _unique_event_type(name: str) -> str:
    return f"itest.{name}.{int(time.time() * 1000)}"


def test_publish_and_consume_round_trip():
    event_type = _unique_event_type("round_trip")
    received = []
    register(event_type, lambda payload, envelope, **kwargs: received.append(payload))

    broker = RedisStreamsBroker(
        service_name="itest_service",
        options={"URL": REDIS_URL, "STREAM_PREFIX": "itest"},
    )
    consumer = broker.listen({event_type})

    broker.publish(
        EventEnvelope(
            event_type=event_type, source_service="itest_service", payload={"n": 1}
        )
    )
    envelope = next(consumer)

    assert dispatch(broker, envelope) is True
    assert received == [{"n": 1}]

    broker.close()


def test_failed_handler_is_dead_lettered_after_max_retries():
    event_type = _unique_event_type("dlq")

    def always_fails(**kwargs):
        raise RuntimeError("boom")

    register(event_type, always_fails)

    broker = RedisStreamsBroker(
        service_name="itest_service",
        options={"URL": REDIS_URL, "STREAM_PREFIX": "itest", "MAX_RETRIES": 1},
    )
    consumer = broker.listen({event_type})

    broker.publish(
        EventEnvelope(event_type=event_type, source_service="itest_service", payload={})
    )
    envelope = next(consumer)

    assert dispatch(broker, envelope) is False
    assert broker.redis.xlen(broker._dlq_name(event_type)) == 1

    broker.close()
