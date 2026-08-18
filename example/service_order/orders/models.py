from django.db import models

from django_event_bus.remote import RemoteForeignKey


class Order(models.Model):
    """Commande locale référençant un utilisateur détenu par service_auth.

    `user_id` est une colonne entière ordinaire (migrations normales,
    `makemigrations`/`migrate` fonctionnent comme pour n'importe quel
    IntegerField). `order.user` (nom dérivé de `user_id`, comme une
    ForeignKey classique) résout l'utilisateur:

    1. d'abord dans le cache Django (`REMOTE_DATA["DEFAULT_TTL"]`
       secondes, `locmem` en dev/tests, Redis en prod via
       `django-redis` si configuré) ;
    2. sinon via le transport configuré (`REMOTE_DATA["DEFAULT_TRANSPORT"]`,
       ici "http" — changez-le en "grpc" pour utiliser l'autre chemin,
       exposé par la même déclaration @expose_resource côté
       service_auth, voir example/service_auth/accounts/resources.py) ;

    ce module ne connaît ni l'URL ni le port de service_auth: cette
    information vit uniquement dans REMOTE_DATA["SERVICE_REGISTRY"]
    (service_order/settings.py).

    `invalidate_on=["auth.user_updated"]`: quand service_auth publie cet
    événement (voir service_auth/accounts/events.py), le cache de
    l'utilisateur concerné est vidé automatiquement — le prochain accès
    à `order.user` re-déclenche un fetch HTTP/gRPC au lieu de renvoyer
    une valeur périmée. C'est la combinaison des deux volets de la
    librairie (bus d'événements + RemoteForeignKey) qui rend ça possible
    sans code supplémentaire ici.
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
