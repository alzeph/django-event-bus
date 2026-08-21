import time

import pytest
from confluent_kafka import KafkaException
from confluent_kafka import Producer as _KafkaProducer

from django_event_bus.brokers.kafka import KafkaBroker
from django_event_bus.dispatcher import dispatch
from django_event_bus.envelope import EventEnvelope
from django_event_bus.registry import register

BOOTSTRAP_SERVERS = "localhost:9092"


def _kafka_available() -> bool:
    try:
        _KafkaProducer({"bootstrap.servers": BOOTSTRAP_SERVERS}).list_topics(timeout=2)
        return True
    except KafkaException:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _kafka_available(), reason="Kafka indisponible sur localhost:9092"
    ),
]


def _unique_event_type(name: str) -> str:
    return f"itest.{name}.{int(time.time() * 1000)}"


def _make_broker(**extra_options):
    return KafkaBroker(
        service_name="itest_service",
        options={
            "BOOTSTRAP_SERVERS": BOOTSTRAP_SERVERS,
            "TOPIC_PREFIX": "itest",
            "POLL_TIMEOUT": 0.2,
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
    from confluent_kafka import Consumer

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

    # Le topic dead-letter n'est jamais souscrit par nom d'event_type
    # applicatif: on le vérifie ici par son nom complet, avec un
    # consumer Kafka brut plutôt qu'un KafkaBroker.
    dlq_consumer = Consumer(
        {
            "bootstrap.servers": BOOTSTRAP_SERVERS,
            "group.id": "itest_dlq_verifier",
            "auto.offset.reset": "earliest",
        }
    )
    dlq_consumer.subscribe([f"itest.{event_type}.dlq"])
    msg = dlq_consumer.poll(5)
    assert msg is not None
    assert msg.error() is None
    dlq_consumer.close()

    broker.close()


def test_retry_then_success_after_republish():
    """Un échec sous MAX_RETRIES republie l'événement (compteur
    incrémenté) sur le même topic plutôt que de le dead-letter — le
    chemin de retry réel, pas seulement le chemin d'abandon."""
    event_type = _unique_event_type("retry_success")
    attempts = []

    def flaky(**kwargs):
        attempts.append(1)
        if len(attempts) < 2:
            raise RuntimeError("échoue au premier essai")

    register(event_type, flaky)

    broker = _make_broker(MAX_RETRIES=3)
    consumer = broker.listen({event_type})

    broker.publish(
        EventEnvelope(event_type=event_type, source_service="itest_service", payload={})
    )

    first = next(consumer)
    assert dispatch(broker, first) is False
    assert len(attempts) == 1

    second = next(consumer)
    assert second.event_id == first.event_id  # même événement republié

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
