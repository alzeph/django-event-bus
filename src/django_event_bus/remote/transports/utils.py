"""Chargement des transports et résolution du registre de services.

Transport loading and service registry resolution.
"""

from __future__ import annotations

import threading
from typing import Any

from django.core.signals import setting_changed
from django.dispatch import receiver as django_receiver
from django.utils.module_loading import import_string

from ...exceptions import RemoteServiceMisconfiguredError
from ...settings import remote_settings
from .base import BaseTransport

#: Noms courts vers chemin pointé, résolus par :func:`load_transport`.
#: Short names to dotted path, resolved by :func:`load_transport`.
_BUILTIN_TRANSPORTS: dict[str, str] = {
    "http": "django_event_bus.remote.transports.http.HTTPTransport",
    "grpc": "django_event_bus.remote.transports.grpc.GRPCTransport",
}

_transports: dict[str, BaseTransport] = {}
_transports_lock = threading.Lock()


def registry_entry(service: str, transport_name: str) -> dict[str, Any]:
    """Renvoie la config d'un service pour un transport donné dans ``SERVICE_REGISTRY``.

    Lève ``RemoteServiceMisconfiguredError`` si le service ou le transport
    demandé n'y figure pas — plutôt qu'un ``KeyError`` brut, pour donner
    au développeur un message actionnable.

    Returns a service's config for a given transport from
    ``SERVICE_REGISTRY``.

    Raises ``RemoteServiceMisconfiguredError`` if the requested service or
    transport is missing from it — instead of a raw ``KeyError``, to give
    the developer an actionable message.
    """
    registry: dict[str, Any] = remote_settings.SERVICE_REGISTRY
    try:
        service_config = registry[service]
    except KeyError:
        raise RemoteServiceMisconfiguredError(
            f"Service '{service}' absent de REMOTE_DATA['SERVICE_REGISTRY'] / "
            f"missing from REMOTE_DATA['SERVICE_REGISTRY']."
        ) from None
    try:
        return service_config[transport_name]
    except KeyError:
        raise RemoteServiceMisconfiguredError(
            f"Transport '{transport_name}' non configuré pour le service '{service}' / "
            f"not configured for service '{service}'."
        ) from None


def load_transport(name: str | None = None) -> BaseTransport:
    """Instancie (et met en cache) le transport désigné par ``name``.

    ``name`` peut être un nom court connu (``"http"``, ``"grpc"``) ou un
    chemin pointé vers une classe personnalisée (même mécanisme que
    ``brokers.utils.load_broker``). Si omis, utilise
    ``REMOTE_DATA["DEFAULT_TRANSPORT"]``. Une seule instance est créée par
    nom de transport et réutilisée (connexions/canaux mis en commun).

    Instantiates (and caches) the transport designated by ``name``.

    ``name`` can be a known short name (``"http"``, ``"grpc"``) or a
    dotted path to a custom class (same mechanism as
    ``brokers.utils.load_broker``). If omitted, uses
    ``REMOTE_DATA["DEFAULT_TRANSPORT"]``. Only one instance is created per
    transport name and reused (pooled connections/channels).
    """
    name = name or remote_settings.DEFAULT_TRANSPORT
    if name in _transports:
        return _transports[name]

    with _transports_lock:
        if name not in _transports:
            dotted_path = _BUILTIN_TRANSPORTS.get(name, name)
            transport_cls = import_string(dotted_path)
            _transports[name] = transport_cls()
    return _transports[name]


def reset_transports() -> None:
    """Ferme et oublie les transports mis en cache. Utile entre deux tests.

    Closes and forgets the cached transports. Useful between tests.
    """
    with _transports_lock:
        for transport in _transports.values():
            transport.close()
        _transports.clear()


@django_receiver(setting_changed)
def _on_setting_changed(*, setting: str, **kwargs: Any) -> None:
    """Réinitialise les transports mis en cache si ``REMOTE_DATA`` change.

    Resets the cached transports if ``REMOTE_DATA`` changes.
    """
    if setting == "REMOTE_DATA":
        reset_transports()
