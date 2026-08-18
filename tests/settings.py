SECRET_KEY = "test"
USE_TZ = True

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

INSTALLED_APPS = [
    "django_event_bus",
    "tests.testapp",
]

EVENT_BUS = {
    "SERVICE_NAME": "test_service",
    "BACKEND": "django_event_bus.brokers.locmem.LocMemBroker",
}

REMOTE_DATA = {
    "DEFAULT_TRANSPORT": "tests.fakes.FakeTransport",
    "DEFAULT_TTL": 60,
    "SERVICE_REGISTRY": {
        "service_auth": {
            "http": {"base_url": "http://testserver/api", "timeout": 3},
            "grpc": {"target": "localhost:50999", "timeout": 3},
        },
    },
}
