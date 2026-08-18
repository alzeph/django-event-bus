"""Commande ``manage.py eventbus_worker``.

``manage.py eventbus_worker`` command.
"""

from __future__ import annotations

import signal
from typing import Any

from django.core.management.base import BaseCommand

from django_event_bus.brokers.utils import get_broker
from django_event_bus.dispatcher import dispatch
from django_event_bus.registry import registered_event_types
from django_event_bus.settings import app_settings


class Command(BaseCommand):
    """Consomme en boucle les événements auxquels ce service est abonné.

    Consumes, in a loop, the events this service is subscribed to.
    """

    help = (
        "Démarre un worker qui consomme les événements inter-services "
        "auxquels ce service est abonné (voir les events.py des apps "
        "installées) et les distribue aux @receiver enregistrés."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        """Boucle bloquante de consommation, arrêt propre sur SIGINT/SIGTERM.

        Blocking consumption loop, clean shutdown on SIGINT/SIGTERM.
        """
        event_types = registered_event_types()
        if not event_types:
            self.stdout.write(
                self.style.WARNING(
                    "Aucun @receiver enregistré: rien à consommer. "
                    "Ajoutez un events.py à une app installée."
                )
            )
            return

        self._stop = False
        signal.signal(signal.SIGINT, self._request_stop)
        signal.signal(signal.SIGTERM, self._request_stop)

        broker = get_broker()
        self.stdout.write(
            self.style.SUCCESS(
                f"[{app_settings.SERVICE_NAME}] en écoute sur: "
                f"{', '.join(sorted(event_types))}"
            )
        )
        try:
            for envelope in broker.listen(event_types):
                if self._stop:
                    break
                dispatch(broker, envelope)
        finally:
            broker.close()
            self.stdout.write("Worker arrêté.")

    def _request_stop(self, signum: int, frame: Any) -> None:
        """Positionne le drapeau d'arrêt lu par la boucle de consommation.

        Sets the stop flag read by the consumption loop.
        """
        self._stop = True
