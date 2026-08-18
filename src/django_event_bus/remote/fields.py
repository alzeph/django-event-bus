"""Champ de modèle ``RemoteForeignKey``.

``RemoteForeignKey`` model field.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from django.db import models

from ..settings import remote_settings
from .cache import get_cache, remote_cache_key
from .invalidation import register_invalidation
from .objects import RemoteObject
from .transports.utils import load_transport


def resolve(
    *,
    service: str,
    resource: str,
    pk: Any,
    transport_name: str | None,
    ttl: int | None,
) -> RemoteObject | None:
    """Résout une ressource distante: cache, sinon transport, puis remise en cache.

    ``None`` si la ressource n'existe pas côté service source. Les
    erreurs réseau/serveur remontent telles quelles depuis le transport
    (``exceptions.RemoteServiceUnavailableError``): une donnée indisponible
    doit être visible par l'appelant, pas masquée.

    Resolves a remote resource: cache, otherwise transport, then re-cache.

    ``None`` if the resource does not exist on the source service.
    Network/server errors propagate as-is from the transport
    (``exceptions.RemoteServiceUnavailableError``): an unavailable resource
    must be visible to the caller, not hidden.
    """
    cache = get_cache()
    key = remote_cache_key(service, resource, pk)

    data = cache.get(key)
    if data is None:
        transport = load_transport(transport_name)
        data = transport.fetch(service=service, resource=resource, pk=pk)
        if data is None:
            # Pas de cache négatif: un futur accès retentera l'appel
            # distant plutôt que de rester bloqué sur une absence
            # temporaire (le service source peut être en cours de
            # démarrage, la ressource pas encore créée, ...).
            #
            # No negative caching: a future access will retry the
            # remote call rather than getting stuck on a temporary
            # absence (the source service may still be starting up, the
            # resource not yet created, ...).
            return None
        effective_ttl = ttl if ttl is not None else remote_settings.DEFAULT_TTL
        cache.set(key, data, timeout=effective_ttl)

    return RemoteObject(service=service, resource=resource, pk=pk, data=data)


class RemoteForeignKeyDescriptor:
    """Descripteur résolvant paresseusement la ressource distante à chaque accès.

    Mis en place par ``RemoteForeignKey.contribute_to_class`` sous le nom
    d'accesseur (ex. ``order.user``), séparé du champ de stockage du PK
    (``order.user_id``) — exactement le clivage attribut/``*_id`` d'une
    ``ForeignKey`` Django classique.

    Descriptor lazily resolving the remote resource on each access.

    Set up by ``RemoteForeignKey.contribute_to_class`` under the accessor
    name (e.g. ``order.user``), separate from the PK storage field
    (``order.user_id``) — exactly the attribute/``*_id`` split of a
    regular Django ``ForeignKey``.
    """

    def __init__(self, field: RemoteForeignKey) -> None:
        """Reçoit le champ ``RemoteForeignKey`` propriétaire de ce descripteur.

        Receives the ``RemoteForeignKey`` field that owns this descriptor.
        """
        self.field = field

    def __get__(self, instance: models.Model | None, owner: type | None = None) -> Any:
        """Renvoie le descripteur lui-même sur la classe, sinon la ressource résolue.

        Returns the descriptor itself on the class, otherwise the resolved resource.
        """
        if instance is None:
            return self
        pk = getattr(instance, self.field.attname)
        if pk is None:
            return None
        return resolve(
            service=self.field.service,
            resource=self.field.resource,
            pk=pk,
            transport_name=self.field.transport_name,
            ttl=self.field.ttl,
        )

    def __set__(self, instance: models.Model, value: Any) -> None:
        """Accepte un PK brut, ou un ``RemoteObject`` dont le ``.pk`` est alors extrait.

        Accepts a raw PK or a ``RemoteObject`` (whose ``.pk`` is then extracted).
        """
        if isinstance(value, RemoteObject):
            value = value.pk
        setattr(instance, self.field.attname, value)


def _default_accessor_name(field_name: str) -> str:
    """Dérive le nom d'accesseur par défaut à partir du nom du champ.

    ``user_id`` -> ``user`` (convention ``ForeignKey``); sinon
    ``{field_name}_remote`` pour ne pas entrer en conflit avec le champ
    de stockage lui-même.

    Derives the default accessor name from the field name.

    ``user_id`` -> ``user`` (``ForeignKey`` convention); otherwise
    ``{field_name}_remote`` to avoid clashing with the storage field
    itself.
    """
    if field_name.endswith("_id"):
        return field_name[: -len("_id")]
    return f"{field_name}_remote"


class RemoteForeignKey(models.BigIntegerField):
    """Champ stockant le PK d'une ressource détenue par un autre service.

    Se comporte, côté stockage, comme une colonne entière classique
    (``makemigrations``/``migrate`` fonctionnent normalement). Côté
    lecture, expose sous le nom d'accesseur (``user`` pour ``user_id``)
    un ``RemoteObject`` résolu paresseusement via cache Django puis, si
    absent ou expiré, via le transport HTTP ou gRPC configuré — sans que
    ce service ait besoin de connaître l'URL du service source.

    Field storing the PK of a resource owned by another service.

    On the storage side, behaves like a regular integer column
    (``makemigrations``/``migrate`` work normally). On the read side,
    exposes under the accessor name (``user`` for ``user_id``) a
    ``RemoteObject`` lazily resolved via the Django cache then, if
    missing or expired, via the configured HTTP or gRPC transport —
    without this service needing to know the source service's URL.
    """

    def __init__(
        self,
        service: str,
        resource: str,
        *,
        transport: str | None = None,
        ttl: int | None = None,
        invalidate_on: Sequence[str] = (),
        accessor_name: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Configure le service/ressource ciblés et les options de résolution.

        ``service``: nom du service source (clé de ``SERVICE_REGISTRY``).
        ``resource``: nom de la ressource chez ce service (ex. ``"users"``).
        ``transport``: nom court (``"http"``/``"grpc"``) ou chemin
        pointé; par défaut ``REMOTE_DATA["DEFAULT_TRANSPORT"]``.
        ``ttl``: durée de cache en secondes; par défaut
        ``REMOTE_DATA["DEFAULT_TTL"]``.
        ``invalidate_on``: types d'événements du bus dont la réception
        doit invalider le cache de cette ressource.
        ``accessor_name``: nom de l'attribut de résolution; par défaut
        dérivé du nom du champ (voir ``_default_accessor_name``).

        Configures the targeted service/resource and resolution options.

        ``service``: source service name (key in ``SERVICE_REGISTRY``).
        ``resource``: resource name on that service (e.g. ``"users"``).
        ``transport``: short name (``"http"``/``"grpc"``) or dotted
        path; defaults to ``REMOTE_DATA["DEFAULT_TRANSPORT"]``.
        ``ttl``: cache duration in seconds; defaults to
        ``REMOTE_DATA["DEFAULT_TTL"]``.
        ``invalidate_on``: bus event types whose receipt should
        invalidate this resource's cache.
        ``accessor_name``: name of the resolving attribute; defaults to
        one derived from the field name (see ``_default_accessor_name``).
        """
        self.service = service
        self.resource = resource
        self.transport_name = transport
        self.ttl = ttl
        self.invalidate_on = tuple(invalidate_on)
        self.accessor_name = accessor_name
        kwargs.setdefault("db_index", True)
        super().__init__(**kwargs)

    def contribute_to_class(
        self, cls: type[models.Model], name: str, private_only: bool = False
    ) -> None:
        """Enregistre la colonne de stockage puis attache le descripteur de résolution.

        Registers the storage column then attaches the resolving descriptor.
        """
        super().contribute_to_class(cls, name, private_only=private_only)
        accessor = self.accessor_name or _default_accessor_name(name)
        setattr(cls, accessor, RemoteForeignKeyDescriptor(self))
        if self.invalidate_on:
            register_invalidation(self.service, self.resource, self.invalidate_on)

    def deconstruct(self) -> tuple[str, str, Sequence[Any], dict[str, Any]]:
        """Sérialise les arguments propres au champ pour les migrations Django.

        Serializes the field's own arguments for Django migrations.
        """
        name, path, args, kwargs = super().deconstruct()
        kwargs.update(
            {
                "service": self.service,
                "resource": self.resource,
                "transport": self.transport_name,
                "ttl": self.ttl,
                "invalidate_on": self.invalidate_on,
                "accessor_name": self.accessor_name,
            }
        )
        return name, path, args, kwargs
