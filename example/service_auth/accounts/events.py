from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver as django_receiver

from django_event_bus import RemoteSignal

# Déclaré une fois, comme un django.dispatch.Signal classique.
user_created = RemoteSignal("auth.user_created")


@django_receiver(post_save, sender=User)
def publish_user_created(sender, instance, created, **kwargs):
    """Pont entre le signal Django local (post_save) et le bus
    inter-services: aucune configuration Redis/Kafka à faire ici, aucune
    connaissance de qui écoute (service_order ou un autre)."""
    if created:
        user_created.send(
            payload={
                "id": instance.id,
                "username": instance.username,
                "email": instance.email,
            }
        )
