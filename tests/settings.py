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
