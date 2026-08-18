from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver as django_receiver

from django_event_bus import RemoteSignal

# Déclarés une fois, comme des django.dispatch.Signal classiques.
user_created = RemoteSignal("auth.user_created")
user_updated = RemoteSignal("auth.user_updated")


def _payload(instance):
    return {"id": instance.id, "username": instance.username, "email": instance.email}


@django_receiver(post_save, sender=User)
def publish_user_saved(sender, instance, created, **kwargs):
    """Pont entre le signal Django local (post_save) et le bus
    inter-services: aucune configuration Redis/Kafka à faire ici, aucune
    connaissance de qui écoute (service_order ou un autre). `user_updated`
    est aussi ce qui invalide le cache RemoteForeignKey côté service_order
    (voir orders/models.py: invalidate_on=["auth.user_updated"])."""
    if created:
        user_created.send(payload=_payload(instance))
    else:
        user_updated.send(payload=_payload(instance))
