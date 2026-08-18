from django.db.models.signals import post_save
from django.dispatch import receiver as django_receiver

from django_event_bus import RemoteSignal, receiver

from .models import Order, ReceivedEvent


@receiver("auth.user_created")
def on_user_created(payload, envelope, **kwargs):
    """service_order n'importe rien de service_auth: il ne connaît que le
    nom de l'événement. C'est le point clé de la démo."""
    ReceivedEvent.objects.create(event_type=envelope.event_type, payload=payload)
    print(
        f"[service_order] utilisateur reçu depuis {envelope.source_service}: {payload}"
    )


# Même pattern que service_auth/accounts/events.py: c'est ce qui permet
# à service_auth de savoir qu'une commande épinglée (OrderBookmark) a
# changé et d'invalider son cache RemoteForeignKey.
order_created = RemoteSignal("orders.order_created")
order_updated = RemoteSignal("orders.order_updated")


def _order_payload(instance: Order) -> dict:
    return {
        "id": instance.id,
        "reference": instance.reference,
        "user_id": instance.user_id,
    }


@django_receiver(post_save, sender=Order)
def publish_order_saved(sender, instance, created, **kwargs):
    if created:
        order_created.send(payload=_order_payload(instance))
    else:
        order_updated.send(payload=_order_payload(instance))
