"""Exceptions de la librairie.

Library exceptions.
"""

from __future__ import annotations


class EventBusError(Exception):
    """Base des erreurs de ``django_event_bus``.

    Base class for ``django_event_bus`` errors.
    """


class ImproperlyConfiguredError(EventBusError):
    """``EVENT_BUS`` ou ``REMOTE_DATA`` mal ou pas configuré dans les settings Django.

    ``EVENT_BUS`` or ``REMOTE_DATA`` missing or misconfigured in the Django settings.
    """


class BrokerError(EventBusError):
    """Erreur de communication avec le broker (Redis, Kafka, ...).

    Communication error with the broker (Redis, Kafka, ...).
    """


class RemoteServiceUnavailableError(EventBusError):
    """Le service distant n'a pas pu être joint (réseau, timeout, erreur serveur).

    Volontairement bruyant: une donnée distante indisponible doit être
    visible et traitée par l'appelant, pas avalée silencieusement — à la
    différence d'un « non trouvé » (404), qui renvoie ``None``.

    The remote service could not be reached (network, timeout, server error).

    Deliberately loud: an unavailable remote resource must be visible and
    handled by the caller, not silently swallowed — unlike a "not found"
    (404), which returns ``None``.
    """


class RemoteServiceMisconfiguredError(EventBusError):
    """Service ou transport absent de ``REMOTE_DATA["SERVICE_REGISTRY"]``.

    Service or transport missing from ``REMOTE_DATA["SERVICE_REGISTRY"]``.
    """
