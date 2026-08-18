"""Accès au cache Django utilisé pour les données distantes.

Access to the Django cache used for remote data.
"""

from __future__ import annotations

from typing import Any

from django.core.cache import BaseCache, caches

from ..settings import remote_settings

_KEY_PREFIX = "django_event_bus:remote"


def get_cache() -> BaseCache:
    """Renvoie le cache Django configuré via ``REMOTE_DATA["CACHE_ALIAS"]``.

    Réutilise le framework de cache de Django (``django.core.cache``)
    plutôt que de gérer une connexion Redis dédiée: n'importe quel
    backend de cache Django (Redis via ``django-redis``, ``locmem`` en
    dev/tests, Memcached, ...) fonctionne sans code supplémentaire.

    Returns the Django cache configured via ``REMOTE_DATA["CACHE_ALIAS"]``.

    Reuses Django's cache framework (``django.core.cache``) instead of
    managing a dedicated Redis connection: any Django cache backend
    (Redis via ``django-redis``, ``locmem`` for dev/tests, Memcached,
    ...) works without extra code.
    """
    return caches[remote_settings.CACHE_ALIAS]


def remote_cache_key(service: str, resource: str, pk: Any) -> str:
    """Construit la clé de cache d'une ressource distante identifiée par son PK.

    Builds the cache key of a remote resource identified by its PK.
    """
    return f"{_KEY_PREFIX}:{service}:{resource}:{pk}"
