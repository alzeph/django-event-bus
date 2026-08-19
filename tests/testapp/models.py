from django.db import models

from django_event_bus.remote import RemoteForeignKey


class Order(models.Model):
    user_id = RemoteForeignKey(
        service="service_auth",
        resource="users",
        invalidate_on=["auth.user_updated"],
    )


class Ticket(models.Model):
    """Modèle dédié aux scénarios de nommage d'accesseur non standard."""

    # Nom de champ ne se terminant pas par "_id": l'accesseur par défaut
    # devient "assignee_remote" plutôt que d'entrer en collision avec le
    # champ de stockage lui-même.
    assignee = RemoteForeignKey(service="service_auth", resource="users")

    # accessor_name explicite, indépendant du nom du champ.
    owner_id = RemoteForeignKey(
        service="service_auth", resource="users", accessor_name="owner_account"
    )


class Widget(models.Model):
    """Modèle dédié aux tests de ``ResourceSerializer``/``expose_resource``."""

    name = models.CharField(max_length=64)
    price_cents = models.IntegerField()


class WidgetOwner(models.Model):
    """Modèle dédié au test de validation précoce d'un champ relation exposé
    sans getter."""

    widget = models.ForeignKey(Widget, on_delete=models.CASCADE)
