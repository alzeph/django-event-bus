"""Résolution paresseuse des settings EVENT_BUS.

Reprend le pattern de `rest_framework.settings.api_settings` : un objet
unique, mis en cache par attribut, invalidé sur le signal
`setting_changed` (utile pour `override_settings` dans les tests). Ce
pattern est déjà connu des développeurs Django/DRF, ce qui sert la DX.
"""

from __future__ import annotations

from django.conf import settings as django_settings
from django.core.signals import setting_changed
from django.dispatch import receiver as django_receiver

from .exceptions import ImproperlyConfigured

DEFAULTS: dict[str, object] = {
    "SERVICE_NAME": None,
    "BACKEND": "django_event_bus.brokers.locmem.LocMemBroker",
    "OPTIONS": {},
    "SERIALIZER": "django_event_bus.serializers.JSONEventSerializer",
}

REQUIRED = {"SERVICE_NAME"}


class EventBusSettings:
    def __init__(self, defaults: dict[str, object]):
        self.defaults = defaults
        self._cache: dict[str, object] = {}

    @property
    def user_settings(self) -> dict[str, object]:
        return getattr(django_settings, "EVENT_BUS", {})

    def __getattr__(self, attr: str):
        if attr not in self.defaults:
            raise AttributeError(f"Setting EVENT_BUS['{attr}'] inconnu")
        if attr in self._cache:
            return self._cache[attr]

        value = self.user_settings.get(attr, self.defaults[attr])
        if attr in REQUIRED and value is None:
            raise ImproperlyConfigured(
                f"EVENT_BUS['{attr}'] est obligatoire. "
                "Ajoutez-le dans les settings Django du service, ex: "
                '`EVENT_BUS = {"SERVICE_NAME": "service_auth", ...}`.'
            )
        if isinstance(value, dict):
            # Copie défensive: sans elle, tous les appelants (et, pour
            # OPTIONS non surchargé, toutes les instances de broker créées
            # ensuite) partageraient et pourraient muter le même dict.
            value = dict(value)
        self._cache[attr] = value
        return value

    def reload(self) -> None:
        self._cache.clear()


app_settings = EventBusSettings(DEFAULTS)


@django_receiver(setting_changed)
def _on_setting_changed(*, setting, **kwargs):
    if setting == "EVENT_BUS":
        app_settings.reload()
