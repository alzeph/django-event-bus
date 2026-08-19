"""Vue HTTP générique servant les ressources déclarées via ``@expose_resource``.

Generic HTTP view serving the resources declared via ``@expose_resource``.
"""

from __future__ import annotations

import hmac

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

from ..settings import remote_settings
from .resources import get_registered_serializer


def _is_authorized(request: HttpRequest) -> bool:
    """Vérifie ``Authorization: Bearer <REMOTE_DATA["AUTH_TOKEN"]>`` si configuré.

    Toujours ``True`` si ``AUTH_TOKEN`` n'est pas défini (comportement par
    défaut, inchangé — voir ``SECURITY.md``). Comparaison à temps constant
    (``hmac.compare_digest``) pour ne pas exposer le secret à une attaque
    par mesure de temps.

    Checks ``Authorization: Bearer <REMOTE_DATA["AUTH_TOKEN"]>`` if configured.

    Always ``True`` if ``AUTH_TOKEN`` is not set (default, unchanged
    behavior — see ``SECURITY.md``). Constant-time comparison
    (``hmac.compare_digest``) so as not to expose the secret to a timing
    attack.
    """
    token = remote_settings.AUTH_TOKEN
    if not token:
        return True
    presented = request.headers.get("Authorization", "")
    expected = f"Bearer {token}"
    return hmac.compare_digest(presented, expected)


@require_GET
def resource_detail(request: HttpRequest, resource: str, pk: str) -> JsonResponse:
    """Répond à ``GET {base_url}/{resource}/{pk}/``, la convention de ``HTTPTransport``.

    404 si ``resource`` n'a pas été exposée via ``@expose_resource``, ou
    si ``pk`` ne correspond à aucune instance (y compris un ``pk`` d'un
    type incompatible, ex: non numérique pour une clé entière — traité
    comme "non trouvé", pas comme une erreur serveur). 401 si
    ``REMOTE_DATA["AUTH_TOKEN"]`` est configuré et que la requête ne
    présente pas le ``Authorization: Bearer <token>`` attendu.

    Answers ``GET {base_url}/{resource}/{pk}/``, ``HTTPTransport``'s convention.

    404 if ``resource`` was not exposed via ``@expose_resource``, or if
    ``pk`` matches no instance (including a ``pk`` of an incompatible
    type, e.g. non-numeric for an integer key — treated as "not found",
    not as a server error). 401 if ``REMOTE_DATA["AUTH_TOKEN"]`` is
    configured and the request does not present the expected
    ``Authorization: Bearer <token>``.
    """
    if not _is_authorized(request):
        return JsonResponse({"detail": "unauthorized"}, status=401)

    serializer_class = get_registered_serializer(resource)
    if serializer_class is None:
        return JsonResponse({"detail": "unknown resource"}, status=404)

    try:
        instance = serializer_class.get_queryset().get(pk=pk)
    except (ObjectDoesNotExist, ValueError, TypeError, ValidationError):
        return JsonResponse({"detail": "not found"}, status=404)

    return JsonResponse(serializer_class(instance).data)
