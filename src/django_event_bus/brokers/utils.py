"""Chargement et cycle de vie du broker partagé.

Loading and lifecycle of the shared broker.
"""

from __future__ import annotations

import threading
from typing import Any

from django.core.signals import setting_changed
from django.dispatch import receiver as django_receiver
from django.utils.module_loading import import_string

from ..settings import app_settings
from .base import BaseBroker


def load_broker() -> BaseBroker:
    """Instancie le broker configuré via `EVENT_BUS["BACKEND"]`.

    Réutilise `django.utils.module_loading.import_string`, le même
    mécanisme que Django pour résoudre `CACHES`/`STORAGES`/`EMAIL_BACKEND`.

    Instantiates the broker configured via `EVENT_BUS["BACKEND"]`.

    Reuses `django.utils.module_loading.import_string`, the same
    mechanism Django uses to resolve `CACHES`/`STORAGES`/`EMAIL_BACKEND`.
    """
    broker_cls = import_string(app_settings.BACKEND)
    return broker_cls(
        service_name=app_settings.SERVICE_NAME, options=app_settings.OPTIONS
    )


_broker: BaseBroker | None = None
_broker_lock = threading.Lock()


def get_broker() -> BaseBroker:
    """Broker partagé (une seule connexion) pour la durée du process.

    Double-checked locking: sous un serveur d'appli multi-thread
    (gunicorn/uwsgi --threads, ...), plusieurs requêtes peuvent atteindre
    `RemoteSignal.send()` avant que le broker n'ait été créé. Sans
    verrou, chacune instancierait sa propre connexion et toutes sauf une
    seraient aussitôt jetées sans être fermées.

    Shared broker (a single connection) for the process's lifetime.

    Double-checked locking: under a multi-threaded app server
    (gunicorn/uwsgi --threads, ...), several requests may reach
    `RemoteSignal.send()` before the broker has been created. Without a
    lock, each would instantiate its own connection and all but one
    would be immediately discarded without being closed.
    """
    global _broker
    if _broker is None:
        with _broker_lock:
            if _broker is None:
                _broker = load_broker()
    return _broker


def reset_broker() -> None:
    """Ferme et oublie le broker partagé.

    Utile entre deux tests, ou après un changement de settings
    (`override_settings(EVENT_BUS=...)`).

    Closes and forgets the shared broker.

    Useful between tests, or after a settings change
    (`override_settings(EVENT_BUS=...)`).
    """
    global _broker
    with _broker_lock:
        if _broker is not None:
            _broker.close()
        _broker = None


@django_receiver(setting_changed)
def _on_setting_changed(*, setting: str, **kwargs: Any) -> None:
    """Réinitialise le broker partagé si ``EVENT_BUS`` change.

    Garde le broker partagé synchronisé avec app_settings (settings.py),
    qui s'invalide déjà sur ce même signal: sans ça, un override de
    EVENT_BUS en cours de process (tests, notamment) laisserait le
    broker pointer vers l'ancien backend/options.

    Resets the shared broker if ``EVENT_BUS`` changes.

    Keeps the shared broker in sync with app_settings (settings.py),
    which already invalidates itself on this same signal: without this,
    overriding EVENT_BUS mid-process (in tests, notably) would leave the
    broker pointing at the old backend/options.
    """
    if setting == "EVENT_BUS":
        reset_broker()
