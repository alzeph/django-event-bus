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

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Ce service publie des événements ; il n'a besoin de rien connaître des
# autres services (ni leur code, ni leur URL), juste de Redis.
EVENT_BUS = {
    "SERVICE_NAME": "service_auth",
    "BACKEND": "django_event_bus.brokers.redis_streams.RedisStreamsBroker",
    "OPTIONS": {"URL": "redis://localhost:6379/0"},
}

# Ce service est ici la SOURCE de données: il n'a pas besoin de
# SERVICE_REGISTRY (il ne consomme aucun RemoteForeignKey lui-même). Il
# n'a même pas besoin de GRPC_RESOLVER: dès qu'une ressource est
# déclarée via @expose_resource (voir accounts/resources.py), le
# résolveur générique de la librairie répond automatiquement en gRPC
# comme en HTTP — REMOTE_DATA n'a donc rien à configurer ici.
