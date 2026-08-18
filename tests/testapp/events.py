from django_event_bus import receiver

received: list[dict] = []


@receiver("testapp.autodiscovered")
def on_autodiscovered(payload, envelope, **kwargs):
    received.append(payload)
