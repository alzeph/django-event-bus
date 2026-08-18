from django_event_bus.brokers.locmem import LocMemBroker
from django_event_bus.envelope import EventEnvelope


def test_fan_out_to_multiple_subscribed_services():
    """Deux services distincts abonnés au même event_type reçoivent
    chacun leur propre copie de l'événement (fan-out), sans se le
    partager comme le ferait un consumer group Redis."""
    event_type = "locmem.fanout.event"

    broker_auth = LocMemBroker(service_name="service_auth_test", options={})
    broker_order = LocMemBroker(service_name="service_order_test", options={})
    consumer_auth = broker_auth.listen({event_type})
    consumer_order = broker_order.listen({event_type})

    published = EventEnvelope(
        event_type=event_type, source_service="publisher", payload={"x": 1}
    )
    broker_auth.publish(published)

    received_by_auth = next(consumer_auth)
    received_by_order = next(consumer_order)

    assert received_by_auth.event_id == published.event_id
    assert received_by_order.event_id == published.event_id


def test_publish_before_any_subscriber_is_lost():
    """LocMemBroker ne fait pas de rejeu: publier avant qu'un service ne
    soit abonné à cet event_type ne lui livre rien (documente une
    limite assumée du backend de dev/tests, à la différence de
    RedisStreamsBroker qui persiste sur le stream)."""
    event_type = "locmem.no_subscriber.event"
    broker = LocMemBroker(service_name="late_subscriber", options={})

    broker.publish(
        EventEnvelope(event_type=event_type, source_service="publisher", payload={})
    )

    consumer = broker.listen({event_type})
    broker.publish(
        EventEnvelope(
            event_type=event_type, source_service="publisher", payload={"seen": True}
        )
    )

    received = next(consumer)
    assert received.payload == {"seen": True}
