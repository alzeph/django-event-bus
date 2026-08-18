"""Configuration de l'application ``django_event_bus``.

``django_event_bus`` application configuration.
"""

from django.apps import AppConfig
from django.utils.module_loading import autodiscover_modules


class DjangoEventBusConfig(AppConfig):
    """Déclenche l'autodiscovery des ``events.py`` au démarrage de Django.

    Triggers the autodiscovery of ``events.py`` modules at Django startup.
    """

    name = "django_event_bus"
    verbose_name = "Event Bus"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        """Importe le ``events.py`` de chaque app installée.

        Même mécanisme que ``admin.autodiscover()``: importer ces
        modules exécute les ``@receiver(...)`` et enregistre les
        abonnements avant que le worker (ou tout appel à
        ``RemoteSignal.send``) n'en ait besoin.

        Imports each installed app's ``events.py``.

        Same mechanism as ``admin.autodiscover()``: importing these
        modules runs the ``@receiver(...)`` decorators and registers the
        subscriptions before the worker (or any call to
        ``RemoteSignal.send``) needs them.
        """
        autodiscover_modules("events")
