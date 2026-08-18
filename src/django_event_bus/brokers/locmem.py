from __future__ import annotations

import queue
import threading
from collections.abc import Iterator

from ..envelope import EventEnvelope
from .base import BaseBroker

_lock = threading.Lock()
_subscribers: dict[str, set[str]] = {}
_queues: dict[tuple[str, str], queue.Queue[EventEnvelope]] = {}


class LocMemBroker(BaseBroker):
    """Broker 100% en mémoire, partagé au sein du process Python.

    Utile pour les tests unitaires et le développement local sans
    dépendance externe. Ne fonctionne PAS entre process/services
    distincts: c'est le rôle du backend Redis (ou d'un futur Kafka).
    Backend par défaut de la librairie, pour qu'un `pip install` seul
    suffise à faire tourner les tests sans infra.
    """

    def publish(self, envelope: EventEnvelope) -> None:
        with _lock:
            for service_name, event_types in _subscribers.items():
                if envelope.event_type in event_types:
                    _queues[(service_name, envelope.event_type)].put(envelope)

    def listen(self, event_types: set[str]) -> Iterator[EventEnvelope]:
        # L'inscription se fait ici, de façon synchrone à l'appel: une
        # fonction génératrice n'exécute rien avant le premier next(), ce
        # qui laisserait une fenêtre où un publish() juste après l'appel
        # à listen() serait perdu faute d'abonné encore enregistré.
        with _lock:
            _subscribers.setdefault(self.service_name, set()).update(event_types)
            for event_type in event_types:
                _queues.setdefault((self.service_name, event_type), queue.Queue())
        return self._consume(event_types)

    def _consume(self, event_types: set[str]) -> Iterator[EventEnvelope]:
        while True:
            for event_type in event_types:
                q = _queues[(self.service_name, event_type)]
                try:
                    yield q.get(timeout=0.1)
                except queue.Empty:
                    continue

    def ack(self, envelope: EventEnvelope) -> None:
        pass

    def fail(self, envelope: EventEnvelope) -> bool:
        return True

    @classmethod
    def reset(cls) -> None:
        """Vide l'état partagé entre process. À appeler entre deux tests."""
        with _lock:
            _subscribers.clear()
            _queues.clear()
