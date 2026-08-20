"""Backends d'authentification pour les endpoints distants exposés.

Interface commune à ``resource_detail`` (HTTP) et au serveur gRPC
générique, pour que les deux transports partagent la même logique de
décision et le même vocabulaire côté audit (``AuthResult``).

Authentication backends for the exposed remote endpoints.

Common interface for ``resource_detail`` (HTTP) and the generic gRPC
server, so both transports share the same decision logic and the same
audit vocabulary (``AuthResult``).
"""

from __future__ import annotations

import hmac
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from django.utils.module_loading import import_string

from ..exceptions import ImproperlyConfiguredError
from ..settings import remote_settings

_BEARER_PREFIX = "Bearer "


@dataclass(frozen=True)
class AuthResult:
    """Issue d'une tentative d'authentification: décision + détails d'audit.

    ``caller`` identifie l'appelant quand le backend le permet (ex: le
    ``sub`` d'un JWT) — ``None`` pour un backend qui ne distingue pas les
    appelants (ex: un secret partagé unique).

    Outcome of an authentication attempt: decision + audit details.

    ``caller`` identifies the caller when the backend allows it (e.g. a
    JWT's ``sub``) — ``None`` for a backend that cannot distinguish
    between callers (e.g. a single shared secret).
    """

    granted: bool
    caller: str | None = None
    reason: str | None = None

    @classmethod
    def allow(cls, *, caller: str | None = None) -> AuthResult:
        """Construit un résultat positif, avec l'identité de l'appelant si connue.

        Builds a positive result, with the caller's identity if known.
        """
        return cls(granted=True, caller=caller)

    @classmethod
    def deny(cls, reason: str) -> AuthResult:
        """Construit un résultat négatif, avec la raison du refus (pour l'audit).

        Builds a negative result, with the denial reason (for auditing).
        """
        return cls(granted=False, reason=reason)


class BaseAuthBackend(ABC):
    """Interface des backends d'authentification.

    Reçoit la valeur brute de l'en-tête (HTTP) ou de la métadonnée
    (gRPC) ``authorization`` — ``None`` si absente — et décide si
    l'appel est autorisé.

    Interface for authentication backends.

    Receives the raw value of the ``authorization`` header (HTTP) or
    metadata entry (gRPC) — ``None`` if absent — and decides whether the
    call is authorized.
    """

    @abstractmethod
    def authenticate(self, authorization: str | None) -> AuthResult:
        """Décide si ``authorization`` autorise l'appel.

        Decides whether ``authorization`` authorizes the call.
        """


class AllowAllAuthBackend(BaseAuthBackend):
    """Backend par défaut: aucune vérification (comportement historique).

    Default backend: no check (historical/default behavior).
    """

    def authenticate(self, authorization: str | None) -> AuthResult:
        """Autorise systématiquement, sans identité d'appelant.

        Always authorizes, with no caller identity.
        """
        return AuthResult.allow()


class StaticTokenAuthBackend(BaseAuthBackend):
    """Secret partagé statique: exige ``Authorization: Bearer <token>``.

    Comparaison à temps constant (``hmac.compare_digest``). Un seul
    secret pour tous les appelants: pas d'identité par appelant, pas
    d'expiration, pas de rotation sans redéployer le service — voir
    ``JWTAuthBackend`` pour lever ces trois limites.

    Static shared secret: requires ``Authorization: Bearer <token>``.

    Constant-time comparison (``hmac.compare_digest``). One secret for
    every caller: no per-caller identity, no expiry, no rotation without
    redeploying the service — see ``JWTAuthBackend`` to lift these three
    limitations.
    """

    def __init__(self, token: str) -> None:
        """Mémorise le token attendu (préfixé une fois pour la comparaison).

        Stores the expected token (prefixed once for the comparison).
        """
        self._expected = f"{_BEARER_PREFIX}{token}"

    def authenticate(self, authorization: str | None) -> AuthResult:
        """Compare ``authorization`` au token attendu, à temps constant.

        Compares ``authorization`` to the expected token, in constant time.
        """
        presented = authorization or ""
        if not hmac.compare_digest(presented, self._expected):
            return AuthResult.deny("invalid or missing shared token")
        return AuthResult.allow(caller="shared-token")


class JWTAuthBackend(BaseAuthBackend):
    """Vérifie un JWT signé porté en ``Authorization: Bearer <jwt>``.

    Chaque appelant présente un token signé par une autorité de
    confiance, avec sa propre expiration (``exp``, obligatoire ici) —
    d'où une identité par appelant (revendication ``sub``) et une durée
    de vie courte gérées par l'émetteur du token, sans avoir à faire
    tourner un secret partagé unique. Nécessite ``pyjwt`` installé
    (extra ``django-event-bus[jwt]``), importé paresseusement pour ne
    pas forcer cette dépendance sur les projets qui n'utilisent pas ce
    backend.

    Verifies a signed JWT carried as ``Authorization: Bearer <jwt>``.

    Each caller presents a token signed by a trusted authority, with its
    own expiry (``exp``, required here) — hence a per-caller identity
    (``sub`` claim) and a short lifetime managed by whatever issues the
    token, without having to rotate one shared secret. Requires
    ``pyjwt`` to be installed (``django-event-bus[jwt]`` extra), lazily
    imported so as not to force this dependency on projects that don't
    use this backend.
    """

    def __init__(
        self,
        key: str,
        *,
        algorithms: Sequence[str] = ("HS256",),
        audience: str | None = None,
        issuer: str | None = None,
        leeway: float = 0,
    ) -> None:
        """Configure la clé/les algorithmes de vérification et les revendications.

        Configures the verification key/algorithms and expected claims.
        """
        try:
            import jwt
        except ImportError as exc:
            raise ImproperlyConfiguredError(
                "JWTAuthBackend nécessite PyJWT, non installé / requires PyJWT, "
                "not installed. `pip install django-event-bus[jwt]`."
            ) from exc
        self._jwt = jwt
        self._key = key
        self._algorithms = list(algorithms)
        self._audience = audience
        self._issuer = issuer
        self._leeway = leeway

    def authenticate(self, authorization: str | None) -> AuthResult:
        """Vérifie la signature, l'expiration et les revendications du JWT présenté.

        Verifies the presented JWT's signature, expiry, and claims.
        """
        if not authorization or not authorization.startswith(_BEARER_PREFIX):
            return AuthResult.deny("missing bearer JWT")
        token = authorization[len(_BEARER_PREFIX) :]
        try:
            claims: dict[str, Any] = self._jwt.decode(
                token,
                self._key,
                algorithms=self._algorithms,
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": ["exp"]},
            )
        except self._jwt.InvalidTokenError as exc:
            return AuthResult.deny(f"invalid JWT: {exc}")
        caller = claims.get("sub") or claims.get("iss")
        return AuthResult.allow(caller=str(caller) if caller else None)


def resolve_auth_backend() -> BaseAuthBackend:
    """Résout le backend actif depuis ``REMOTE_DATA``.

    ``AUTH_BACKEND`` (chemin pointé vers une instance, ou une classe
    instanciée sans argument) est prioritaire; sinon ``AUTH_TOKEN`` sert
    de raccourci vers ``StaticTokenAuthBackend``; sinon aucune
    vérification (``AllowAllAuthBackend``, comportement par défaut).

    Resolves the active backend from ``REMOTE_DATA``.

    ``AUTH_BACKEND`` (dotted path to an instance, or a class instantiated
    with no argument) takes precedence; otherwise ``AUTH_TOKEN`` acts as
    a shorthand for ``StaticTokenAuthBackend``; otherwise no check
    (``AllowAllAuthBackend``, the default behavior).
    """
    backend_path = remote_settings.AUTH_BACKEND
    if backend_path:
        backend = import_string(backend_path)
        if isinstance(backend, type):
            backend = backend()
        return backend  # type: ignore[no-any-return]

    token = remote_settings.AUTH_TOKEN
    if token:
        return StaticTokenAuthBackend(token)

    return AllowAllAuthBackend()
