"""Expose le modèle Order de ce service aux autres services.

Miroir exact de service_auth/accounts/resources.py: c'est cette
déclaration qui permet à service_auth (via OrderBookmark, voir
accounts/models.py) de lire une commande sans connaître l'URL de
service_order.
"""

from django_event_bus.remote import ResourceSerializer, expose_resource

from .models import Order


@expose_resource
class OrderResourceSerializer(ResourceSerializer):
    class Meta:
        model = Order
        # Doit correspondre au `resource=` du RemoteForeignKey côté
        # service_auth (voir example/service_auth/accounts/models.py).
        resource = "orders"
        fields = ["id", "reference", "user_id"]
