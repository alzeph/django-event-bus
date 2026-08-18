import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "demo-service-auth"
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django_event_bus",
    "accounts",
]

MIDDLEWARE = []
ROOT_URLCONF = "service_auth.urls"

# SQLITE_PATH: configurable pour que Docker Compose puisse monter un
# volume nommé sur un chemin dédié (ex: /data/db.sqlite3) sans recouvrir
# le code de l'image — monter un volume directement sur BASE_DIR
# masquerait les fichiers Python copiés dans l'image par un volume vide
# au premier démarrage.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("SQLITE_PATH", str(BASE_DIR / "db.sqlite3")),
    }
}

USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Cache PARTAGÉ (pas le locmem implicite par défaut de Django): ce
# service tourne en plusieurs process (runserver, remote_grpc_server,
# eventbus_worker, un manage.py shell ponctuel, ...). Avec un cache
# locmem, chacun aurait sa propre mémoire isolée et l'invalidation
# faite par eventbus_worker (voir accounts/models.py::OrderBookmark)
# n'aurait jamais d'effet sur le cache vu par runserver — le bug est
# silencieux (aucune erreur, juste une donnée qui ne se rafraîchit
# jamais). D'où un vrai cache Redis, partagé entre tous les process de
# ce service.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.environ.get("CACHE_REDIS_URL", "redis://localhost:6379/1"),
    }
}

# REDIS_URL/SERVICE_ORDER_HTTP_BASE_URL: valeurs par défaut = ce qu'il
# faut pour lancer les process à la main sur localhost (voir le README).
# En Docker Compose, ces variables sont redéfinies avec les noms de
# service du réseau interne (ex: "http://service_order_http:8000/api")
# — c'est le seul endroit qui change entre les deux façons de lancer la
# démo, le reste du code est identique.
EVENT_BUS = {
    "SERVICE_NAME": "service_auth",
    "BACKEND": "django_event_bus.brokers.redis_streams.RedisStreamsBroker",
    "OPTIONS": {"URL": os.environ.get("REDIS_URL", "redis://localhost:6379/0")},
}

# Ce service est à la fois SOURCE de données (accounts/resources.py,
# lu par service_order) et CONSOMMATEUR (OrderBookmark, voir
# accounts/models.py, qui lit une commande détenue par service_order) —
# la démo montre l'échange dans les deux sens. Aucun GRPC_RESOLVER à
# configurer: dès qu'une ressource est déclarée via @expose_resource,
# le résolveur générique de la librairie répond automatiquement en gRPC
# comme en HTTP.
REMOTE_DATA = {
    "SERVICE_REGISTRY": {
        "service_order": {
            "http": {
                "base_url": os.environ.get(
                    "SERVICE_ORDER_HTTP_BASE_URL", "http://localhost:8002/api"
                ),
                "timeout": 3,
            },
        },
    },
    "DEFAULT_TRANSPORT": "http",
    "DEFAULT_TTL": 30,
}
