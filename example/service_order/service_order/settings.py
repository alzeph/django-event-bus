import os
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

# SQLITE_PATH: voir le commentaire équivalent dans
# service_auth/settings.py (nécessaire pour le volume Docker Compose).
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("SQLITE_PATH", str(BASE_DIR / "db.sqlite3")),
    }
}

USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Cache PARTAGÉ: voir le commentaire équivalent dans
# service_auth/settings.py — sans lui, l'invalidation faite par
# eventbus_worker n'aurait aucun effet sur le cache de runserver.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.environ.get("CACHE_REDIS_URL", "redis://localhost:6379/1"),
    }
}

# Ce service ne connaît ni le code ni l'URL de service_auth: il ne
# s'abonne qu'à un nom d'événement ("auth.user_created").
EVENT_BUS = {
    "SERVICE_NAME": "service_order",
    "BACKEND": "django_event_bus.brokers.redis_streams.RedisStreamsBroker",
    "OPTIONS": {
        "URL": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        "BLOCK_MS": 2000,
    },
}

# SERVICE_AUTH_HTTP_BASE_URL/SERVICE_AUTH_GRPC_TARGET: valeurs par
# défaut = ce qu'il faut pour lancer les process à la main sur
# localhost (voir le README). En Docker Compose, ces variables sont
# redéfinies avec les noms de service du réseau interne — c'est le seul
# endroit qui change entre les deux façons de lancer la démo.
#
# Ce service est aussi SOURCE de données (orders/resources.py, lu par
# service_auth via OrderBookmark — sens 2 de la démo).
REMOTE_DATA = {
    "SERVICE_REGISTRY": {
        "service_auth": {
            "http": {
                "base_url": os.environ.get(
                    "SERVICE_AUTH_HTTP_BASE_URL", "http://localhost:8001/api"
                ),
                "timeout": 3,
            },
            "grpc": {
                "target": os.environ.get("SERVICE_AUTH_GRPC_TARGET", "localhost:50051"),
                "timeout": 3,
            },
        },
    },
    # "http" par défaut ; passez à "grpc" pour basculer sur l'autre
    # transport sans changer une ligne côté service_auth ni dans
    # orders/models.py (voir le README pour l'essayer).
    "DEFAULT_TRANSPORT": "http",
    "DEFAULT_TTL": 30,
}
