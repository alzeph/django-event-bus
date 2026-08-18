"""Interface commune des transports de récupération de données distantes.

Common interface for remote data-fetching transports.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseTransport(ABC):
    """Interface que tout transport (HTTP, gRPC, ...) doit implémenter.

    Chargé dynamiquement depuis ``REMOTE_DATA["DEFAULT_TRANSPORT"]`` ou le
    ``transport`` explicite d'un ``RemoteForeignKey``: c'est cette
    interface qui permet de changer de transport sans toucher au reste de
    la librairie ni au code applicatif — même principe que
    ``brokers.base.BaseBroker`` pour le bus d'événements.

    Interface that every transport (HTTP, gRPC, ...) must implement.

    Loaded dynamically from ``REMOTE_DATA["DEFAULT_TRANSPORT"]`` or a
    ``RemoteForeignKey``'s explicit ``transport``: this interface is what
    allows swapping the transport without touching the rest of the
    library or application code — the same principle as
    ``brokers.base.BaseBroker`` for the event bus.
    """

    @abstractmethod
    def fetch(self, *, service: str, resource: str, pk: Any) -> dict[str, Any] | None:
        """Récupère une ressource distante par son PK.

        Renvoie ``None`` si la ressource n'existe pas côté service source
        (équivalent d'un 404 HTTP). Lève
        ``exceptions.RemoteServiceUnavailableError`` si le service n'a pas pu
        être joint ou a répondu une erreur.

        Fetches a remote resource by its PK.

        Returns ``None`` if the resource does not exist on the source
        service (HTTP 404 equivalent). Raises
        ``exceptions.RemoteServiceUnavailableError`` if the service could not
        be reached or responded with an error.
        """

    def close(self) -> None:  # noqa: B027 - no-op volontaire, pas de comportement requis par défaut
        """Libère les ressources (connexions, canaux, ...). No-op par défaut.

        Releases resources (connections, channels, ...). No-op by default.
        """
