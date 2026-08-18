"""Expose le modèle User de ce service aux autres services.

Autodécouvert au démarrage (comme events.py) : cette seule déclaration
suffit à répondre aux requêtes HTTP *et* gRPC de service_order, sans
qu'aucune vue ni aucun résolveur gRPC n'ait besoin d'être écrit à la main.
"""

from django.contrib.auth.models import User

from django_event_bus.remote import ResourceSerializer, expose_resource


@expose_resource
class UserResourceSerializer(ResourceSerializer):
    class Meta:
        model = User
        # Doit correspondre au `resource=` du RemoteForeignKey côté
        # service_order (voir example/service_order/orders/models.py).
        resource = "users"
        fields = ["id", "username", "email", "full_name"]

    def get_full_name(self, instance):
        """Champ calculé: pas une colonne du modèle, construit à la demande.

        Convention get_<champ>, identique à SerializerMethodField de
        Django REST Framework: dès qu'une méthode get_full_name existe,
        elle remplace l'accès direct à l'attribut "full_name" (qui
        n'existe pas sur User) pour ce champ précis.
        """
        full_name = f"{instance.first_name} {instance.last_name}".strip()
        return full_name or instance.username
