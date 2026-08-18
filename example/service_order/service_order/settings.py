from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "demo-service-order"
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django_event_bus",
    "orders",
]

MIDDLEWARE = []
ROOT_URLCONF = "service_order.urls"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Ce service ne connaît ni le code ni l'URL de service_auth: il ne
# s'abonne qu'à un nom d'événement ("auth.user_created").
EVENT_BUS = {
    "SERVICE_NAME": "service_order",
    "BACKEND": "django_event_bus.brokers.redis_streams.RedisStreamsBroker",
    "OPTIONS": {"URL": "redis://localhost:6379/0", "BLOCK_MS": 2000},
}

# L'URL de service_auth n'est configurée qu'ici, une seule fois: le code
# applicatif (orders/models.py) ne fait que "RemoteForeignKey(service=
# "service_auth", resource="users")" et order.user.email, sans jamais
# manipuler d'URL, de client HTTP ou de canal gRPC.
REMOTE_DATA = {
    "SERVICE_REGISTRY": {
        "service_auth": {
            "http": {"base_url": "http://localhost:8001/api", "timeout": 3},
            "grpc": {"target": "localhost:50051", "timeout": 3},
        },
    },
    "DEFAULT_TRANSPORT": "http",
    "DEFAULT_TTL": 30,
}
