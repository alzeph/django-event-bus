from django_event_bus import receiver

from .models import ReceivedEvent


@receiver("auth.user_created")
def on_user_created(payload, envelope, **kwargs):
    """service_order n'importe rien de service_auth: il ne connaît que le
    nom de l'événement. C'est le point clé de la démo."""
    ReceivedEvent.objects.create(event_type=envelope.event_type, payload=payload)
    print(
        f"[service_order] utilisateur reçu depuis {envelope.source_service}: {payload}"
    )
