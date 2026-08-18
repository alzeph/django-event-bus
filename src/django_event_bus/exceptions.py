class EventBusError(Exception):
    """Base des erreurs de django_event_bus."""


class ImproperlyConfigured(EventBusError):
    """EVENT_BUS mal ou pas configuré dans les settings Django."""


class BrokerError(EventBusError):
    """Erreur de communication avec le broker (Redis, Kafka, ...)."""
