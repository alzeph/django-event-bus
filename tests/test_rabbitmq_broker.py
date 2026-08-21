import time

import pika
import pytest

from django_event_bus.brokers.rabbitmq import RabbitMQBroker
from django_event_bus.dispatcher import dispatch
from django_event_bus.envelope import EventEnvelope
from django_event_bus.registry import register

RABBITMQ_URL = "amqp://guest:guest@localhost:5672/%2F"


def _rabbitmq_available() -> bool:
    try:
        pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL)).close()
        return True
    except Exception:  # noqa: BLE001 - simple probe, toute erreur => indisponible
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _rabbitmq_available(), reason="RabbitMQ indisponible sur localhost:5672"
    ),
]


def _unique_event_type(name: str) -> str:
    return f"itest.{name}.{int(time.time() * 1000)}"


def _make_broker(**extra_options):
    return RabbitMQBroker(
        service_name="itest_service",
        options={
            "URL": RABBITMQ_URL,
            "EXCHANGE_PREFIX": "itest",
            "POLL_INTERVAL": 0.2,
            "RETRY_DELAY_MS": 200,
            **extra_options,
        },
    )


def test_publish_and_consume_round_trip():
    event_type = _unique_event_type("round_trip")
    received = []
    register(event_type, lambda payload, envelope, **kwargs: received.append(payload))

    broker = _make_broker()
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

    broker = _make_broker(MAX_RETRIES=1)
    consumer = broker.listen({event_type})

    broker.publish(
        EventEnvelope(event_type=event_type, source_service="itest_service", payload={})
    )
    envelope = next(consumer)

    assert dispatch(broker, envelope) is False

    connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
    channel = connection.channel()
    method_frame, _, _ = channel.basic_get(
        f"itest.itest_service.{event_type}.dlq", auto_ack=True
    )
    assert method_frame is not None
    connection.close()

    broker.close()


def test_retry_then_success_after_ttl_requeue():
    """Un échec sous MAX_RETRIES ne dead-lettre pas: le message part
    dans la file de retry puis, son TTL expiré, revient dans la file
    principale — le chemin de retry réel, pas seulement l'abandon."""
    event_type = _unique_event_type("retry_success")
    attempts = []

    def flaky(**kwargs):
        attempts.append(1)
        if len(attempts) < 2:
            raise RuntimeError("échoue au premier essai")

    register(event_type, flaky)

    broker = _make_broker(MAX_RETRIES=3, RETRY_DELAY_MS=200)
    consumer = broker.listen({event_type})

    broker.publish(
        EventEnvelope(event_type=event_type, source_service="itest_service", payload={})
    )

    first = next(consumer)
    assert dispatch(broker, first) is False
    assert len(attempts) == 1

    second = next(consumer)
    assert second.event_id == first.event_id  # même message repris, pas un nouveau

    assert dispatch(broker, second) is True
    assert len(attempts) == 2

    broker.close()


def test_listen_receives_events_of_multiple_types():
    type_a = _unique_event_type("multi_type_a")
    type_b = _unique_event_type("multi_type_b")

    broker = _make_broker()
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
