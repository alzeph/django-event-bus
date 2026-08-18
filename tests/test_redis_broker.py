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


def test_retry_then_success_after_idle_reclaim():
    """Un échec sous MAX_RETRIES ne dead-lettre pas: le message reste
    pending puis, une fois RETRY_IDLE_MS dépassé, XAUTOCLAIM le reprend
    et un second essai peut réussir — le chemin de retry réel, pas
    seulement le chemin d'abandon déjà couvert ci-dessus."""
    event_type = _unique_event_type("retry_success")
    attempts = []

    def flaky(**kwargs):
        attempts.append(1)
        if len(attempts) < 2:
            raise RuntimeError("échoue au premier essai")

    register(event_type, flaky)

    broker = RedisStreamsBroker(
        service_name="itest_service",
        options={
            "URL": REDIS_URL,
            "STREAM_PREFIX": "itest",
            "MAX_RETRIES": 3,
            "RETRY_IDLE_MS": 200,
        },
    )
    consumer = broker.listen({event_type})

    broker.publish(
        EventEnvelope(event_type=event_type, source_service="itest_service", payload={})
    )

    first = next(consumer)
    assert dispatch(broker, first) is False
    assert len(attempts) == 1
    assert broker.redis.xlen(broker._dlq_name(event_type)) == 0

    time.sleep(0.3)  # dépasse RETRY_IDLE_MS: le message devient réclamable

    second = next(consumer)
    assert second.event_id == first.event_id  # même message repris, pas un nouveau

    assert dispatch(broker, second) is True
    assert len(attempts) == 2
    assert broker.redis.xlen(broker._dlq_name(event_type)) == 0

    pending = broker.redis.xpending(f"itest:{event_type}", "itest_service")
    assert pending["pending"] == 0

    broker.close()


def test_two_consumers_share_group_without_duplicating_messages():
    """Deux workers du même service (même consumer group, CONSUMER_NAME
    distinct) se partagent les messages: chacun peut consommer et
    acquitter indépendamment, sans qu'un message soit livré deux fois."""
    event_type = _unique_event_type("multi_consumer")

    broker_a = RedisStreamsBroker(
        service_name="itest_service",
        options={
            "URL": REDIS_URL,
            "STREAM_PREFIX": "itest",
            "CONSUMER_NAME": "worker-a",
        },
    )
    broker_b = RedisStreamsBroker(
        service_name="itest_service",
        options={
            "URL": REDIS_URL,
            "STREAM_PREFIX": "itest",
            "CONSUMER_NAME": "worker-b",
        },
    )
    consumer_a = broker_a.listen({event_type})
    consumer_b = broker_b.listen({event_type})

    received_ids = []
    published_ids = []
    for i in range(4):
        # Un seul message non livré à la fois: la lecture immédiate qui
        # suit revient forcément à ce message précis, ce qui rend le
        # test déterministe (pas de lot ambigu entre les deux workers).
        envelope = EventEnvelope(
            event_type=event_type, source_service="itest_service", payload={"i": i}
        )
        broker_a.publish(envelope)
        published_ids.append(envelope.event_id)

        active_consumer, active_broker = (
            (consumer_a, broker_a) if i % 2 == 0 else (consumer_b, broker_b)
        )
        received = next(active_consumer)
        assert received.event_id == envelope.event_id
        received_ids.append(received.event_id)
        active_broker.ack(received)

    assert sorted(received_ids) == sorted(published_ids)
    assert len(set(received_ids)) == 4

    broker_a.close()
    broker_b.close()


def test_listen_receives_events_of_multiple_types():
    """Un seul listen() sur plusieurs event_type reçoit bien les
    événements des deux streams, entrelacés au fil de leur publication."""
    type_a = _unique_event_type("multi_type_a")
    type_b = _unique_event_type("multi_type_b")

    broker = RedisStreamsBroker(
        service_name="itest_service",
        options={"URL": REDIS_URL, "STREAM_PREFIX": "itest"},
    )
    consumer = broker.listen({type_a, type_b})

    broker.publish(
        EventEnvelope(
            event_type=type_a, source_service="itest_service", payload={"which": "a"}
        )
    )
    broker.publish(
        EventEnvelope(
            event_type=type_b, source_service="itest_service", payload={"which": "b"}
        )
    )

    received_types = set()
    for _ in range(2):
        envelope = next(consumer)
        received_types.add(envelope.event_type)
        broker.ack(envelope)

    assert received_types == {type_a, type_b}

    broker.close()
