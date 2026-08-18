from django.db import models


class ReceivedEvent(models.Model):
    """Trace persistée de chaque événement inter-services reçu, pour
    prouver concrètement que le flux service_auth -> Redis -> service_order
    fonctionne de bout en bout."""

    event_type = models.CharField(max_length=255)
    payload = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.event_type} @ {self.received_at:%Y-%m-%d %H:%M:%S}"
