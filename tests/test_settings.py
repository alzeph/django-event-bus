import pytest
from django.test import override_settings
from django.utils.module_loading import import_string

from django_event_bus.exceptions import ImproperlyConfiguredError
from django_event_bus.settings import app_settings, remote_settings


def test_missing_service_name_raises_improperly_configured():
    with override_settings(EVENT_BUS={}), pytest.raises(ImproperlyConfiguredError):
        _ = app_settings.SERVICE_NAME


def test_backend_defaults_to_locmem_when_unset():
    with override_settings(EVENT_BUS={"SERVICE_NAME": "svc"}):
        assert app_settings.BACKEND == "django_event_bus.brokers.locmem.LocMemBroker"


def test_grpc_resolver_defaults_to_the_generic_registry_resolver():
    """Sans REMOTE_DATA["GRPC_RESOLVER"] explicite, `manage.py
    remote_grpc_server` doit fonctionner dès qu'une ressource est
    exposée via @expose_resource, sans configuration supplémentaire."""
    from django_event_bus.remote.resources import registry_resolver

    with override_settings(REMOTE_DATA={}):
        resolver = import_string(remote_settings.GRPC_RESOLVER)

    assert resolver is registry_resolver
