from django.conf import settings
from django.db import models

from django_event_bus.remote import RemoteForeignKey


class OrderBookmark(models.Model):
    """Sens 2 de la démo: service_auth lit une donnée détenue par service_order.

    Illustre "la dernière commande épinglée par un utilisateur" — un
    exemple plausible où le service d'authentification a besoin
    d'afficher, sur le profil d'un utilisateur, une information qui vit
    ailleurs. `order_id` fonctionne exactement comme `Order.user_id`
    côté service_order (voir example/service_order/orders/models.py),
    dans l'autre sens: colonne entière ordinaire, résolution paresseuse
    via cache puis HTTP, invalidation sur l'événement publié par
    service_order quand la commande change.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="order_bookmark",
    )
    order_id = RemoteForeignKey(
        service="service_order",
        resource="orders",
        invalidate_on=["orders.order_updated"],
    )

    def __str__(self) -> str:
        return f"{self.user}: commande #{self.order_id}"
