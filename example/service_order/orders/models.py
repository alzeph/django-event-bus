from django.db import models

from django_event_bus.remote import RemoteForeignKey


class Order(models.Model):
    """Commande locale référençant un utilisateur détenu par service_auth.

    `user_id` est une colonne entière ordinaire (migrations normales).
    `order.user` résout l'utilisateur via cache Django puis, si absent,
    HTTP/gRPC vers service_auth — sans que ce module ne connaisse son URL.
    `invalidate_on`: quand service_auth publie "auth.user_updated", le
    cache de cet utilisateur est vidé automatiquement (voir
    django_event_bus.remote.invalidation).
    """

    reference = models.CharField(max_length=64)
    user_id = RemoteForeignKey(
        service="service_auth",
        resource="users",
        invalidate_on=["auth.user_updated"],
    )

    def __str__(self) -> str:
        return self.reference


class ReceivedEvent(models.Model):
    """Trace persistée de chaque événement inter-services reçu, pour
    prouver concrètement que le flux service_auth -> Redis -> service_order
    fonctionne de bout en bout."""

    event_type = models.CharField(max_length=255)
    payload = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.event_type} @ {self.received_at:%Y-%m-%d %H:%M:%S}"
