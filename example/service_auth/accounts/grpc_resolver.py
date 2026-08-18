from django.contrib.auth.models import User


def resolve(resource, pk):
    """Résolveur utilisé par `manage.py remote_grpc_server`.

    Référencé par REMOTE_DATA["GRPC_RESOLVER"].
    """
    if resource != "users":
        return None
    try:
        user = User.objects.get(pk=pk)
    except (User.DoesNotExist, ValueError):
        return None
    return {"id": user.id, "username": user.username, "email": user.email}
