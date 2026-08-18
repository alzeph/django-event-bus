from django.apps import AppConfig
from django.utils.module_loading import autodiscover_modules


class DjangoEventBusConfig(AppConfig):
    name = "django_event_bus"
    verbose_name = "Event Bus"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        # Même mécanisme que admin.autodiscover(): importe le module
        # `events.py` de chaque app installée, ce qui exécute les
        # @receiver(...) et enregistre les abonnements avant que le
        # worker (ou tout appel à RemoteSignal.send) n'en ait besoin.
        autodiscover_modules("events")
