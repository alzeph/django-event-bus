"""Vue HTTP générique servant les ressources déclarées via ``@expose_resource``.

Generic HTTP view serving the resources declared via ``@expose_resource``.
"""

from __future__ import annotations

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

from ..settings import remote_settings
from . import audit
from .auth import resolve_auth_backend
from .ratelimit import is_allowed, resolve_rate_limit_config
from .resources import get_registered_serializer


@require_GET
def resource_detail(request: HttpRequest, resource: str, pk: str) -> JsonResponse:
    """Répond à ``GET {base_url}/{resource}/{pk}/``, la convention de ``HTTPTransport``.

    Dans l'ordre: 429 si ``REMOTE_DATA["RATE_LIMIT"]`` est dépassé pour
    l'adresse appelante ; 401 si l'authentification configurée
    (``AUTH_BACKEND``/``AUTH_TOKEN``) refuse la requête ; 404 si
    ``resource`` n'a pas été exposée via ``@expose_resource``, ou si
    ``pk`` ne correspond à aucune instance (y compris un ``pk`` d'un
    type incompatible, ex: non numérique pour une clé entière — traité
    comme "non trouvé", pas comme une erreur serveur). Chaque décision
    d'accès (accordée ou refusée) est journalisée via
    ``remote.audit.log_access``.

    Answers ``GET {base_url}/{resource}/{pk}/``, ``HTTPTransport``'s convention.

    In order: 429 if ``REMOTE_DATA["RATE_LIMIT"]`` is exceeded for the
    calling address; 401 if the configured authentication
    (``AUTH_BACKEND``/``AUTH_TOKEN``) rejects the request; 404 if
    ``resource`` was not exposed via ``@expose_resource``, or if ``pk``
    matches no instance (including a ``pk`` of an incompatible type,
    e.g. non-numeric for an integer key — treated as "not found", not as
    a server error). Every access decision (granted or denied) is
    logged via ``remote.audit.log_access``.
    """
    peer = request.META.get("REMOTE_ADDR")

    rate_limit_config = resolve_rate_limit_config(remote_settings.RATE_LIMIT)
    if rate_limit_config is not None and not is_allowed(rate_limit_config, peer or "-"):
        audit.log_access(
            transport="http",
            granted=False,
            peer=peer,
            resource=resource,
            pk=pk,
            reason="rate limited",
        )
        return JsonResponse({"detail": "rate limited"}, status=429)

    auth_result = resolve_auth_backend().authenticate(
        request.headers.get("Authorization")
    )
    if not auth_result.granted:
        audit.log_access(
            transport="http",
            granted=False,
            peer=peer,
            resource=resource,
            pk=pk,
            reason=auth_result.reason,
        )
        return JsonResponse({"detail": "unauthorized"}, status=401)

    audit.log_access(
        transport="http",
        granted=True,
        peer=peer,
        resource=resource,
        pk=pk,
        caller=auth_result.caller,
    )

    serializer_class = get_registered_serializer(resource)
    if serializer_class is None:
        return JsonResponse({"detail": "unknown resource"}, status=404)

    try:
        instance = serializer_class.get_queryset().get(pk=pk)
    except (ObjectDoesNotExist, ValueError, TypeError, ValidationError):
        return JsonResponse({"detail": "not found"}, status=404)

    return JsonResponse(serializer_class(instance).data)
