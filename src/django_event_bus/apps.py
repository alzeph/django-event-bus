"""Configuration de l'application ``django_event_bus``.

``django_event_bus`` application configuration.
"""

from django.apps import AppConfig
from django.utils.module_loading import autodiscover_modules


class DjangoEventBusConfig(AppConfig):
    """Déclenche l'autodiscovery des ``events.py``/``resources.py`` au démarrage.

    Triggers the autodiscovery of ``events.py``/``resources.py`` modules at startup.
    """

    name = "django_event_bus"
    verbose_name = "Event Bus"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        """Importe le ``events.py`` et le ``resources.py`` de chaque app installée.

        Même mécanisme que ``admin.autodiscover()``: importer ces
        modules exécute les ``@receiver(...)`` et ``@expose_resource``
        et enregistre abonnements/ressources avant que le worker, un
        appel à ``RemoteSignal.send`` ou une requête HTTP/gRPC entrante
        n'en aient besoin.

        Imports each installed app's ``events.py`` and ``resources.py``.

        Same mechanism as ``admin.autodiscover()``: importing these
        modules runs the ``@receiver(...)`` and ``@expose_resource``
        decorators and registers subscriptions/resources before the
        worker, a call to ``RemoteSignal.send``, or an incoming
        HTTP/gRPC request needs them.
        """
        autodiscover_modules("events")
        autodiscover_modules("resources")
