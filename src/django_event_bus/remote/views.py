"""Vue HTTP générique servant les ressources déclarées via ``@expose_resource``.

Generic HTTP view serving the resources declared via ``@expose_resource``.
"""

from __future__ import annotations

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.http import HttpRequest, JsonResponse

from .resources import get_registered_serializer


def resource_detail(request: HttpRequest, resource: str, pk: str) -> JsonResponse:
    """Répond à ``GET {base_url}/{resource}/{pk}/``, la convention de ``HTTPTransport``.

    404 si ``resource`` n'a pas été exposée via ``@expose_resource``, ou
    si ``pk`` ne correspond à aucune instance (y compris un ``pk`` d'un
    type incompatible, ex: non numérique pour une clé entière — traité
    comme "non trouvé", pas comme une erreur serveur).

    Answers ``GET {base_url}/{resource}/{pk}/``, ``HTTPTransport``'s convention.

    404 if ``resource`` was not exposed via ``@expose_resource``, or if
    ``pk`` matches no instance (including a ``pk`` of an incompatible
    type, e.g. non-numeric for an integer key — treated as "not found",
    not as a server error).
    """
    serializer_class = get_registered_serializer(resource)
    if serializer_class is None:
        return JsonResponse({"detail": "unknown resource"}, status=404)

    try:
        instance = serializer_class.get_queryset().get(pk=pk)
    except (ObjectDoesNotExist, ValueError, TypeError, ValidationError):
        return JsonResponse({"detail": "not found"}, status=404)

    return JsonResponse(serializer_class(instance).data)
