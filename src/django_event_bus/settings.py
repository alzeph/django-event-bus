"""Résolution paresseuse des sections de settings de la librairie.

Reprend le pattern de ``rest_framework.settings.api_settings`` : un objet
unique par section (``EVENT_BUS``, ``REMOTE_DATA``), mis en cache par
attribut, invalidé sur le signal ``setting_changed`` (utile pour
``override_settings`` dans les tests). Ce pattern est déjà connu des
développeurs Django/DRF, ce qui sert la DX.

Lazy resolution of the library's settings sections.

Mirrors the ``rest_framework.settings.api_settings`` pattern: one object
per section (``EVENT_BUS``, ``REMOTE_DATA``), cached per attribute,
invalidated on the ``setting_changed`` signal (useful for
``override_settings`` in tests). This pattern is already familiar to
Django/DRF developers, which serves the developer experience.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from django.conf import settings as django_settings
from django.core.signals import setting_changed
from django.dispatch import receiver as django_receiver

from .exceptions import ImproperlyConfiguredError


class LazySettings:
    """Section de settings résolue paresseusement depuis ``django.conf.settings``.

    Chaque attribut est lu au premier accès dans le dict Django
    correspondant (``getattr(django_settings, setting_name, {})``), puis
    mis en cache. Les valeurs de type ``dict`` sont copiées avant mise en
    cache pour éviter qu'un appelant ne mute par mégarde la valeur
    partagée (et, pour un setting non surchargé, le dict de defaults
    lui-même).

    Settings section resolved lazily from ``django.conf.settings``.

    Each attribute is read on first access from the corresponding Django
    dict (``getattr(django_settings, setting_name, {})``), then cached.
    Values of type ``dict`` are copied before caching to prevent a caller
    from accidentally mutating the shared value (and, for a setting that
    was not overridden, the defaults dict itself).
    """

    def __init__(
        self,
        setting_name: str,
        defaults: dict[str, Any],
        required: Iterable[str] = (),
    ) -> None:
        """Initialise la section avec son nom de setting Django et ses defaults.

        Initializes the section with its Django setting name and default values.
        """
        self.setting_name = setting_name
        self.defaults = defaults
        self.required = frozenset(required)
        self._cache: dict[str, Any] = {}

    @property
    def user_settings(self) -> dict[str, Any]:
        """Dict brut fourni par le développeur (``{}`` si absent).

        Raw dict provided by the developer (``{}`` if absent).
        """
        return getattr(django_settings, self.setting_name, {})

    def __getattr__(self, attr: str) -> Any:
        """Résout, met en cache puis renvoie la valeur de ``attr``.

        Resolves, caches, then returns the value of ``attr``.
        """
        if attr not in self.defaults:
            raise AttributeError(f"{self.setting_name}['{attr}'] inconnu/unknown")
        if attr in self._cache:
            return self._cache[attr]

        value = self.user_settings.get(attr, self.defaults[attr])
        if attr in self.required and value is None:
            raise ImproperlyConfiguredError(
                f"{self.setting_name}['{attr}'] est obligatoire / is required. "
                "Ajoutez-le dans les settings Django du service, ex / add it to "
                f"the service's Django settings, e.g.: `{self.setting_name} = "
                f'{{"{attr}": ...}}`.'
            )
        if isinstance(value, dict):
            value = dict(value)
        self._cache[attr] = value
        return value

    def reload(self) -> None:
        """Vide le cache: force une relecture des settings au prochain accès.

        Clears the cache: forces settings to be re-read on next access.
        """
        self._cache.clear()


EVENT_BUS_DEFAULTS: dict[str, Any] = {
    "SERVICE_NAME": None,
    "BACKEND": "django_event_bus.brokers.locmem.LocMemBroker",
    "OPTIONS": {},
    "SERIALIZER": "django_event_bus.serializers.JSONEventSerializer",
}

app_settings = LazySettings("EVENT_BUS", EVENT_BUS_DEFAULTS, required={"SERVICE_NAME"})


REMOTE_DATA_DEFAULTS: dict[str, Any] = {
    # {"service_auth": {"http": {"base_url": ..., "timeout": ...}, "grpc": {...}}}
    "SERVICE_REGISTRY": {},
    "DEFAULT_TRANSPORT": "http",
    "DEFAULT_TTL": 60,
    "CACHE_ALIAS": "default",
    # Chemin pointé vers (resource: str, pk: str) -> dict | None, utilisé
    # uniquement par `manage.py remote_grpc_server` (services exposant
    # leurs données en gRPC — pas requis pour les services qui ne font
    # que consommer via RemoteForeignKey). Par défaut: le résolveur
    # générique basé sur @expose_resource, qui couvre le cas standard
    # sans qu'aucun service n'ait à écrire sa propre fonction.
    "GRPC_RESOLVER": "django_event_bus.remote.resources.registry_resolver",
    # Secret partagé optionnel protégeant les endpoints exposés
    # (`resource_detail` HTTP et le serveur gRPC générique): si défini,
    # tout appel sans en-tête/métadonnée `Authorization: Bearer <AUTH_TOKEN>`
    # correspondant est rejeté (401 / UNAUTHENTICATED). `None` par défaut:
    # aucune vérification, comportement inchangé (à réserver à un réseau
    # déjà de confiance — voir SECURITY.md).
    "AUTH_TOKEN": None,
    # Chemin pointé vers un callable sans argument renvoyant des
    # `grpc.ServerCredentials`, utilisé par `manage.py remote_grpc_server`
    # pour servir en TLS (`add_secure_port`) plutôt qu'en clair. `None`
    # par défaut: port non chiffré (`add_insecure_port`), comportement
    # inchangé.
    "GRPC_SERVER_CREDENTIALS": None,
    # Chemin pointé vers une instance de `remote.auth.BaseAuthBackend`
    # (ex: `remote.auth.JWTAuthBackend(...)` construite dans un module de
    # config du service). Prioritaire sur AUTH_TOKEN si les deux sont
    # définis. `None` par défaut: AUTH_TOKEN (ci-dessus) sert alors de
    # raccourci vers `StaticTokenAuthBackend`.
    "AUTH_BACKEND": None,
    # Nombre d'octets max lus depuis une réponse HTTP/gRPC distante avant
    # d'abandonner (RemoteServiceUnavailableError): protège un
    # consommateur contre un pair "de confiance" compromis ou mal
    # configuré renvoyant un corps de réponse démesuré. Surchargeable par
    # service via SERVICE_REGISTRY[service]["http"]["max_response_bytes"].
    "MAX_RESPONSE_BYTES": 2_000_000,
    # Limite de requêtes par appelant (adresse IP HTTP / adresse pair
    # gRPC) sur `resource_detail` et le serveur gRPC générique, dans une
    # fenêtre glissante grossière. `None` désactive. Actif par défaut
    # (contrairement à AUTH_TOKEN): un simple hook n'aurait rien changé
    # pour les services qui ne l'auraient pas branché — voir SECURITY.md.
    "RATE_LIMIT": {"LIMIT": 300, "WINDOW_SECONDS": 60},
    # Si True, refuse de servir/consommer sans TLS: HTTPTransport exige
    # un `base_url` en `https://`, GRPCTransport exige `credentials` dans
    # SERVICE_REGISTRY[service]["grpc"], et `manage.py remote_grpc_server`
    # refuse de démarrer sans GRPC_SERVER_CREDENTIALS. `False` par
    # défaut: comportement inchangé (TLS reste optionnel).
    "REQUIRE_TLS": False,
}

remote_settings = LazySettings("REMOTE_DATA", REMOTE_DATA_DEFAULTS)


@django_receiver(setting_changed)
def _on_setting_changed(*, setting: str, **kwargs: Any) -> None:
    """Invalide le cache de la section concernée quand son setting change.

    Invalidates the affected section's cache when its setting changes.
    """
    if setting == "EVENT_BUS":
        app_settings.reload()
    elif setting == "REMOTE_DATA":
        remote_settings.reload()
