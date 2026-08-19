"""Rate limiting (fenêtre glissante grossière) pour les endpoints distants exposés.

S'appuie sur le cache Django (``REMOTE_DATA["CACHE_ALIAS"]``), déjà
utilisé par ``remote/cache.py`` pour les données distantes: aucune
connexion dédiée à gérer, et un compteur partagé entre tous les
process d'un service dès que ce cache est un backend partagé (Redis,
...) — voir l'avertissement sur ``locmem`` dans le README.

Rate limiting (coarse fixed window) for the exposed remote endpoints.

Built on the Django cache (``REMOTE_DATA["CACHE_ALIAS"]``), already used
by ``remote/cache.py`` for remote data: no dedicated connection to
manage, and a counter shared across every process of a service as soon
as that cache is a shared backend (Redis, ...) — see the ``locmem``
warning in the README.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .cache import get_cache

_KEY_PREFIX = "django_event_bus:remote:ratelimit"


@dataclass(frozen=True)
class RateLimitConfig:
    """Paramètres d'une limite: nombre d'appels max par fenêtre de N secondes.

    Parameters of a limit: max number of calls per N-second window.
    """

    limit: int
    window_seconds: int


def resolve_rate_limit_config(raw: dict[str, Any] | None) -> RateLimitConfig | None:
    """Construit une ``RateLimitConfig`` depuis ``REMOTE_DATA["RATE_LIMIT"]``.

    ``None`` (config absente ou désactivée) désactive la limite.

    Builds a ``RateLimitConfig`` from ``REMOTE_DATA["RATE_LIMIT"]``.

    ``None`` (missing or disabled config) disables the limit.
    """
    if not raw:
        return None
    return RateLimitConfig(
        limit=int(raw["LIMIT"]),
        window_seconds=int(raw.get("WINDOW_SECONDS", 60)),
    )


def is_allowed(config: RateLimitConfig, key: str) -> bool:
    """Décrémente le budget de ``key`` pour la fenêtre courante, renvoie s'il en reste.

    Fenêtre fixe grossière (pas un token bucket): un appelant peut
    dépasser ``limit`` de près du double au voisinage d'une frontière de
    fenêtre. Compromis accepté pour rester à un seul ``cache.incr()`` par
    appel plutôt qu'un ensemble trié / script Lua — suffisant pour une
    protection anti-abus, pas une garantie de débit précise.

    Decrements ``key``'s budget for the current window, returns whether
    any is left.

    Coarse fixed window (not a token bucket): a caller can exceed
    ``limit`` by nearly double near a window boundary. An accepted
    trade-off to stay at one ``cache.incr()`` per call rather than a
    sorted set / Lua script — enough for abuse protection, not a precise
    rate guarantee.
    """
    cache = get_cache()
    window = int(time.time() // config.window_seconds)
    cache_key = f"{_KEY_PREFIX}:{key}:{window}"

    if cache.add(cache_key, 1, timeout=config.window_seconds * 2):
        count = 1
    else:
        try:
            count = cache.incr(cache_key)
        except ValueError:
            # La clé a expiré entre le add() et l'incr(): traité comme
            # une fenêtre neuve plutôt que comme un échec.
            #
            # The key expired between add() and incr(): treated as a
            # fresh window rather than as a failure.
            cache.add(cache_key, 1, timeout=config.window_seconds * 2)
            count = 1

    return count <= config.limit
