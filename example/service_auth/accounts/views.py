from django.contrib.auth.models import User
from django.http import JsonResponse


def get_user(request, pk):
    """Endpoint HTTP consommé par le RemoteForeignKey de service_order.

    Convention attendue par HTTPTransport: GET {base_url}/users/{pk}/ ->
    JSON de la ressource, ou 404 si absente. Une vue Django simple
    suffit, aucun framework REST requis.
    """
    try:
        user = User.objects.get(pk=pk)
    except User.DoesNotExist:
        return JsonResponse({"detail": "not found"}, status=404)
    return JsonResponse({"id": user.id, "username": user.username, "email": user.email})
