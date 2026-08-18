"""Enveloppe autour des données distantes récupérées.

Wrapper around fetched remote data.
"""

from __future__ import annotations

from typing import Any


class RemoteObject:
    """Enveloppe légère et immuable autour du dict renvoyé par un transport.

    Expose les clés du payload distant comme attributs Python (ex.
    ``remote_user.email``) sans être un vrai modèle Django: aucune
    connexion base de données, aucune écriture possible. Deux instances
    sont égales si elles désignent la même ressource distante
    (``service``, ``resource``, ``pk``), indépendamment du contenu
    actuellement en cache.

    Lightweight, immutable wrapper around the dict returned by a
    transport. Exposes the remote payload's keys as Python attributes
    (e.g. ``remote_user.email``) without being a real Django model: no
    database connection, no write support. Two instances are equal if
    they designate the same remote resource (``service``, ``resource``,
    ``pk``), regardless of the currently cached content.
    """

    __slots__ = ("_data", "pk", "resource", "service")

    def __init__(
        self, *, service: str, resource: str, pk: Any, data: dict[str, Any]
    ) -> None:
        """Construit l'enveloppe à partir du payload déjà résolu (cache ou transport).

        Builds the wrapper from an already-resolved payload (cache or transport).
        """
        self.service = service
        self.resource = resource
        self.pk = pk
        self._data = data

    def __getattr__(self, name: str) -> Any:
        """Expose une clé du payload distant comme attribut.

        Exposes a remote payload key as an attribute.
        """
        try:
            return self._data[name]
        except KeyError:
            resource = f"{self.service}.{self.resource}"
            raise AttributeError(
                f"'{resource}' n'a pas de champ / has no field '{name}'"
            ) from None

    def __eq__(self, other: object) -> bool:
        """Compare par identité de ressource distante, pas par contenu.

        Compares by remote resource identity, not by content.
        """
        if not isinstance(other, RemoteObject):
            return NotImplemented
        self_key = (self.service, self.resource, self.pk)
        other_key = (other.service, other.resource, other.pk)
        return self_key == other_key

    def __hash__(self) -> int:
        """Cohérent avec ``__eq__``: basé sur l'identité de la ressource distante.

        Consistent with ``__eq__``: based on the remote resource identity.
        """
        return hash((self.service, self.resource, self.pk))

    def __repr__(self) -> str:
        """Représentation de débogage incluant service/ressource/pk.

        Debug representation including service/resource/pk.
        """
        return f"<RemoteObject {self.service}.{self.resource}#{self.pk!r}>"

    def as_dict(self) -> dict[str, Any]:
        """Copie du payload distant brut.

        Copy of the raw remote payload.
        """
        return dict(self._data)
