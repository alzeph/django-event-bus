import pytest
from django.test import override_settings

from django_event_bus.exceptions import ImproperlyConfiguredError
from django_event_bus.settings import app_settings


def test_missing_service_name_raises_improperly_configured():
    with override_settings(EVENT_BUS={}), pytest.raises(ImproperlyConfiguredError):
        _ = app_settings.SERVICE_NAME


def test_backend_defaults_to_locmem_when_unset():
    with override_settings(EVENT_BUS={"SERVICE_NAME": "svc"}):
        assert app_settings.BACKEND == "django_event_bus.brokers.locmem.LocMemBroker"
