"""Exposition déclarative de modèles comme ressources distantes.

Côté *fournisseur* de données, symétrique de ``fields.py`` (côté
*consommateur*). Un ``ResourceSerializer`` décrit une fois comment
transformer un modèle en dict ; ``@expose_resource`` l'enregistre pour
qu'il réponde automatiquement aux requêtes HTTP (``remote/views.py`` +
``remote/urls.py``) et gRPC (``registry_resolver``, branché par défaut
sur ``REMOTE_DATA["GRPC_RESOLVER"]``) — sans écrire de vue ni de
résolveur à la main.

À ne pas confondre avec ``django_event_bus.serializers.JSONEventSerializer``
(volet bus d'événements), qui sérialise des enveloppes d'événements, pas
des ressources exposées par ``RemoteForeignKey``.

Declarative exposure of models as remote resources.

The *provider* side, symmetric to ``fields.py`` (the *consumer* side). A
``ResourceSerializer`` describes once how to turn a model into a dict;
``@expose_resource`` registers it so it automatically answers HTTP
requests (``remote/views.py`` + ``remote/urls.py``) and gRPC requests
(``registry_resolver``, wired by default into
``REMOTE_DATA["GRPC_RESOLVER"]``) — without hand-writing a view or a
resolver.

Not to be confused with ``django_event_bus.serializers.JSONEventSerializer``
(the event bus side), which serializes event envelopes, not resources
exposed via ``RemoteForeignKey``.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from typing import Any

from django.core.exceptions import (
    FieldDoesNotExist,
    ObjectDoesNotExist,
    ValidationError,
)
from django.db.models import Model, QuerySet

from ..exceptions import ImproperlyConfiguredError

_registry: dict[str, type[ResourceSerializer]] = {}
_registry_lock = threading.Lock()


class ResourceSerializer:
    """Décrit comment transformer un modèle Django en dict exposable.

    Convention façon Django REST Framework, familière par construction :

    * ``Meta.model`` (obligatoire) et ``Meta.resource`` (obligatoire, la
      clé attendue par ``RemoteForeignKey(resource=...)``) ;
    * ``Meta.fields``: liste explicite, ou ``"__all__"`` (défaut) pour
      tous les champs du modèle ; ``Meta.exclude`` en alternative à une
      liste explicite (pas les deux à la fois) ;
    * ``Meta.queryset``: requête de base optionnelle (défaut:
      ``model._default_manager.all()``) ;
    * une méthode ``get_<champ>(self, instance)`` remplace, quand elle
      existe, l'accès direct à l'attribut — pour un champ calculé ou
      renommé (identique à ``SerializerMethodField`` de DRF) ;
    * ``to_representation()`` et ``get_queryset()`` restent surchargeables
      pour un contrôle total (scoping, jointures, format personnalisé).

    Describes how to turn a Django model into an exposable dict.

    Django REST Framework-style convention, familiar by design:

    * ``Meta.model`` (required) and ``Meta.resource`` (required, the key
      expected by ``RemoteForeignKey(resource=...)``);
    * ``Meta.fields``: explicit list, or ``"__all__"`` (default) for all
      of the model's fields; ``Meta.exclude`` as an alternative to an
      explicit list (not both at once);
    * ``Meta.queryset``: optional base query (default:
      ``model._default_manager.all()``);
    * a ``get_<field>(self, instance)`` method replaces, when present,
      the direct attribute access — for a computed or renamed field
      (identical to DRF's ``SerializerMethodField``);
    * ``to_representation()`` and ``get_queryset()`` remain overridable
      for full control (scoping, joins, custom shape).
    """

    class Meta:
        """À redéfinir dans chaque sous-classe (voir la docstring de la classe).

        To be redefined in each subclass (see the class docstring).
        """

        model: type[Model] | None = None
        resource: str | None = None
        fields: Sequence[str] | str = "__all__"
        exclude: Sequence[str] = ()
        queryset: QuerySet[Any] | None = None

    def __init__(self, instance: Model) -> None:
        """Enveloppe l'instance à sérialiser.

        Wraps the instance to serialize.
        """
        self.instance = instance

    @classmethod
    def get_queryset(cls) -> QuerySet[Any]:
        """Requête de base utilisée pour résoudre un PK en instance.

        ``Meta.queryset`` si fourni, sinon ``Meta.model._default_manager.all()``.
        À surcharger pour restreindre la visibilité (ex: exclure les
        lignes soft-deleted) ou optimiser (``select_related``, ...).

        Base query used to resolve a PK into an instance.

        ``Meta.queryset`` if provided, otherwise
        ``Meta.model._default_manager.all()``. Override to restrict
        visibility (e.g. exclude soft-deleted rows) or optimize
        (``select_related``, ...).
        """
        # getattr défensif: la Meta d'une sous-classe est une classe
        # neuve qui n'hérite pas de ResourceSerializer.Meta (comme chez
        # DRF) — seuls les attributs explicitement définis existent.
        #
        # Defensive getattr: a subclass's Meta is a fresh class that
        # does not inherit from ResourceSerializer.Meta (as with DRF) —
        # only explicitly defined attributes exist.
        queryset = getattr(cls.Meta, "queryset", None)
        if queryset is not None:
            return queryset
        model = getattr(cls.Meta, "model", None)
        assert model is not None  # garanti par expose_resource
        return model._default_manager.all()

    @classmethod
    def get_fields(cls) -> list[str]:
        """Résout ``Meta.fields``/``Meta.exclude`` en une liste de noms de champs.

        Resolves ``Meta.fields``/``Meta.exclude`` into a list of field names.
        """
        model = getattr(cls.Meta, "model", None)
        assert model is not None  # garanti par expose_resource
        fields = getattr(cls.Meta, "fields", "__all__")
        exclude = getattr(cls.Meta, "exclude", ())
        if fields != "__all__" and exclude:
            raise ImproperlyConfiguredError(
                f"{cls.__name__}.Meta: 'fields' (liste explicite) et 'exclude' "
                "sont mutuellement exclusifs / are mutually exclusive."
            )
        if fields != "__all__":
            return list(fields)
        all_names = [f.name for f in model._meta.fields]
        return [name for name in all_names if name not in exclude]

    def to_representation(self, instance: Model) -> dict[str, Any]:
        """Construit le dict exposé pour ``instance``.

        Pour chaque champ de ``get_fields()``: utilise ``get_<champ>()``
        si cette méthode existe, sinon lit l'attribut directement.
        Surcharger cette méthode donne un contrôle total, en ignorant
        ``fields``/``get_<champ>``.

        Builds the exposed dict for ``instance``.

        For each field from ``get_fields()``: uses ``get_<field>()`` if
        that method exists, otherwise reads the attribute directly.
        Overriding this method gives full control, bypassing
        ``fields``/``get_<field>``.
        """
        data: dict[str, Any] = {}
        for field_name in self.get_fields():
            getter = getattr(self, f"get_{field_name}", None)
            if getter is not None:
                data[field_name] = getter(instance)
                continue
            try:
                value = getattr(instance, field_name)
            except AttributeError as exc:
                raise ImproperlyConfiguredError(
                    f"{type(self).__name__}: le champ '{field_name}' n'existe pas sur "
                    f"{instance.__class__.__name__} et aucune méthode "
                    f"get_{field_name} n'est définie / field '{field_name}' does not "
                    f"exist on {instance.__class__.__name__} and no get_{field_name} "
                    "method is defined."
                ) from exc
            # Une relation (ForeignKey, ...) n'est pas sérialisable en JSON
            # telle quelle: sans ce garde-fou, l'erreur ne surviendrait
            # qu'au moment de l'encodage JSON, avec un TypeError peu
            # explicite côté HTTP/gRPC.
            #
            # A relation (ForeignKey, ...) is not directly JSON-serializable:
            # without this guard, the failure would only surface at JSON
            # encoding time, as an unhelpful TypeError on the HTTP/gRPC side.
            if isinstance(value, Model):
                raise ImproperlyConfiguredError(
                    f"{type(self).__name__}: le champ '{field_name}' est une relation "
                    f"({value.__class__.__name__}) non sérialisable directement ; "
                    f"définissez get_{field_name}(self, instance) pour choisir quoi "
                    f"exposer / field '{field_name}' is a relation "
                    f"({value.__class__.__name__}) not directly serializable; define "
                    f"a get_{field_name}(self, instance) method to choose what to "
                    "expose."
                )
            data[field_name] = value
        return data

    @property
    def data(self) -> dict[str, Any]:
        """Représentation de ``self.instance`` (raccourci façon DRF).

        Representation of ``self.instance`` (DRF-style shortcut).
        """
        return self.to_representation(self.instance)


def expose_resource(
    serializer_class: type[ResourceSerializer],
) -> type[ResourceSerializer]:
    """Enregistre ``serializer_class`` comme fournisseur de sa ``Meta.resource``.

    S'utilise comme décorateur, façon ``@admin.register`` :

        @expose_resource
        class UserResourceSerializer(ResourceSerializer):
            class Meta:
                model = User
                resource = "users"
                fields = ["id", "username", "email"]

    Idempotent pour la même classe (import répété), mais lève
    ``ImproperlyConfiguredError`` si ``Meta.model``/``Meta.resource``
    manquent, ou si une AUTRE classe a déjà pris ce nom de ressource.

    Registers ``serializer_class`` as the provider for its ``Meta.resource``.

    Used as a decorator, ``@admin.register``-style:

        @expose_resource
        class UserResourceSerializer(ResourceSerializer):
            class Meta:
                model = User
                resource = "users"
                fields = ["id", "username", "email"]

    Idempotent for the same class (repeated import), but raises
    ``ImproperlyConfiguredError`` if ``Meta.model``/``Meta.resource`` are
    missing, or if ANOTHER class already claimed that resource name.
    """
    meta = getattr(serializer_class, "Meta", None)
    model = getattr(meta, "model", None)
    resource = getattr(meta, "resource", None)
    if model is None or resource is None:
        raise ImproperlyConfiguredError(
            f"{serializer_class.__name__}.Meta doit définir 'model' et 'resource' / "
            "must define 'model' and 'resource'."
        )
    _check_no_unserializable_relation_fields(serializer_class, model)
    with _registry_lock:
        existing = _registry.get(resource)
        if existing is not None and existing is not serializer_class:
            raise ImproperlyConfiguredError(
                f"La ressource '{resource}' est déjà exposée par {existing.__name__} "
                f"/ resource '{resource}' is already exposed by {existing.__name__}."
            )
        _registry[resource] = serializer_class
    return serializer_class


def _check_no_unserializable_relation_fields(
    serializer_class: type[ResourceSerializer], model: type[Model]
) -> None:
    """Détecte au chargement un champ relation exposé sans ``get_<champ>``.

    Sans ce garde-fou, l'erreur ne surviendrait qu'à la première requête
    HTTP/gRPC, sous la forme d'un ``TypeError`` peu explicite au moment de
    l'encodage JSON — le même contrôle existe dans
    ``ResourceSerializer.to_representation`` comme filet de sécurité, pour
    les cas non couverts ici (ex: ``Meta.fields``/``Meta.exclude`` mal
    configurés, détecté seulement à l'usage, cf. ci-dessous).

    Detects, at load time, a relation field exposed without a
    ``get_<field>`` method.

    Without this guard, the failure would only surface on the first
    HTTP/gRPC request, as an unhelpful ``TypeError`` at JSON-encoding time
    — the same check exists in ``ResourceSerializer.to_representation`` as
    a safety net, for cases not covered here (e.g. a misconfigured
    ``Meta.fields``/``Meta.exclude``, only caught on use, see below).
    """
    try:
        field_names = serializer_class.get_fields()
    except ImproperlyConfiguredError:
        # 'fields' et 'exclude' mutuellement exclusifs: déjà signalé à
        # l'usage par get_fields() lui-même, rien à valider ici.
        #
        # 'fields' and 'exclude' mutually exclusive: already reported on
        # use by get_fields() itself, nothing to validate here.
        return
    for field_name in field_names:
        if getattr(serializer_class, f"get_{field_name}", None) is not None:
            continue
        try:
            model_field = model._meta.get_field(field_name)
        except FieldDoesNotExist:
            # Pas une colonne du modèle (propriété, champ mal orthographié,
            # ...): déjà couvert à l'usage par le AttributeError de
            # to_representation(), rien à valider ici non plus.
            #
            # Not a model column (property, misspelled field, ...): already
            # covered on use by to_representation()'s AttributeError,
            # nothing to validate here either.
            continue
        if model_field.is_relation:
            raise ImproperlyConfiguredError(
                f"{serializer_class.__name__}: le champ '{field_name}' est une "
                f"relation ({model_field.__class__.__name__}) non sérialisable "
                f"directement ; définissez get_{field_name}(self, instance) pour "
                f"choisir quoi exposer / field '{field_name}' is a relation "
                f"({model_field.__class__.__name__}) not directly serializable; "
                f"define a get_{field_name}(self, instance) method to choose what "
                "to expose."
            )


def get_registered_serializer(
    resource: str,
) -> type[ResourceSerializer] | None:
    """Renvoie le ``ResourceSerializer`` enregistré pour ``resource``, ou ``None``.

    Returns the ``ResourceSerializer`` registered for ``resource``, ``None`` if absent.
    """
    return _registry.get(resource)


def registry_resolver(resource: str, pk: str) -> dict[str, Any] | None:
    """Résolveur générique ``(resource, pk) -> dict | None`` basé sur le registre.

    Résout n'importe quelle ressource déclarée via ``@expose_resource``
    sans code spécifique par service — c'est cette fonction qui sert de
    valeur par défaut à ``REMOTE_DATA["GRPC_RESOLVER"]``
    (``settings.py``) et à la vue HTTP générique (``views.py``).

    Generic ``(resource, pk) -> dict | None`` resolver based on the registry.

    Resolves any resource declared via ``@expose_resource`` with no
    service-specific code — this function is the default value of
    ``REMOTE_DATA["GRPC_RESOLVER"]`` (``settings.py``) and of the
    generic HTTP view (``views.py``).
    """
    serializer_class = get_registered_serializer(resource)
    if serializer_class is None:
        return None
    try:
        instance = serializer_class.get_queryset().get(pk=pk)
    except (ObjectDoesNotExist, ValueError, TypeError, ValidationError):
        return None
    return serializer_class(instance).data


def reset_registry() -> None:
    """Vide le registre de ressources exposées. Utile entre deux tests.

    Clears the exposed-resources registry. Useful between tests.
    """
    with _registry_lock:
        _registry.clear()
