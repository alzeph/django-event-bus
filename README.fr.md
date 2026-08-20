# django-event-bus

[English](README.md) · Français

[![CI](https://github.com/alzeph/django-event-bus/actions/workflows/ci.yml/badge.svg)](https://github.com/alzeph/django-event-bus/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/django-event-bus.svg)](https://pypi.org/project/django-event-bus/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](pyproject.toml)

> **Release candidate.** `django-event-bus` est en `1.0.0rc2` : l'API est
> considérée comme figée mais n'a pas encore été éprouvée par un usage
> réel hors de ce dépôt. Les retours (issues, cas d'usage, bugs) sont
> bienvenus avant de tagger la version finale `1.0.0`.

## Le problème que ça résout

Dans une architecture microservices Django (`service_auth`, `service_order`,
`service_product`, ...), deux besoins reviennent tout le temps :

1. **Prévenir les autres services** qu'un événement métier a eu lieu (un
   utilisateur créé, une commande payée, ...) — sans que chaque service
   n'ait à configurer Redis/Kafka lui-même, ni à connaître qui écoute.
2. **Lire une donnée détenue par un autre service** à partir de son PK
   (l'email d'un utilisateur pour afficher une commande, par exemple) —
   sans écrire de client HTTP à la main ni connaître l'URL du service.

`django-event-bus` répond aux deux avec la même philosophie que Django
lui-même : de la configuration déclarative dans `settings.py`
(`EVENT_BUS`, `REMOTE_DATA` — comme `DATABASES` ou `CACHES`) et des
conventions de fichiers découvertes automatiquement (`events.py`,
`resources.py` — comme `admin.py`), pour qu'un service n'ait quasiment
que des déclarations à écrire, jamais de plomberie réseau.

Ce README est un parcours guidé : chaque section explique *pourquoi* la
pièce existe avant de montrer *comment* l'utiliser. Le dossier `example/`
contient deux vrais mini-projets Django (`service_auth`, `service_order`)
qui font tourner tout ce qui est décrit ici — la section
[Démo à deux services](#démo-à-deux-services--tout-essayer-pour-de-vrai)
donne les commandes exactes à taper.

## Installation

```python
INSTALLED_APPS = [
    ...,
    "django_event_bus",
]
```

C'est tout pour l'installation : pas de migration propre à la librairie,
pas de modèle. Le reste de ce README explique les deux settings
optionnels (`EVENT_BUS`, `REMOTE_DATA`) et les conventions de fichiers
qu'ils activent.

## 1. Émettre et recevoir des événements

### Configurer le bus

```python
EVENT_BUS = {
    "SERVICE_NAME": "service_auth",  # obligatoire: identifie ce service dans les logs/erreurs
    "BACKEND": "django_event_bus.brokers.redis_streams.RedisStreamsBroker",
    "OPTIONS": {"URL": "redis://localhost:6379/0"},
}
```

`BACKEND` est le seul endroit où le broker est choisi. Le backend par
défaut, `django_event_bus.brokers.locmem.LocMemBroker`, ne nécessite
aucune infra (utile en tests/dev — c'est lui qui est utilisé si vous ne
mettez pas `EVENT_BUS` du tout, sauf `SERVICE_NAME` qui reste
obligatoire). Passer à Redis, ou demain à un autre broker qui
implémenterait la même interface, ne change **que** ce dict — aucun
code applicatif à toucher.

### Émettre un événement

```python
# accounts/events.py
from django_event_bus import RemoteSignal

# Déclaré une fois au niveau module, comme un django.dispatch.Signal.
user_created = RemoteSignal("auth.user_created")

# Puis, n'importe où (une vue, un signal post_save, une tâche, ...):
user_created.send(payload={"id": user.id, "email": user.email})
```

La convention de nom `"{service}.{événement}"` (`auth.user_created`)
évite les collisions entre services : chacun préfixe ses événements par
son propre nom.

### Recevoir un événement (dans un autre service)

```python
# orders/events.py
from django_event_bus import receiver

@receiver("auth.user_created")
def on_user_created(payload, envelope, **kwargs):
    ...
```

Tout fichier `events.py` d'une app installée est découvert
automatiquement au démarrage (même mécanisme que `admin.autodiscover()`
— vous n'avez rien à importer manuellement ailleurs). L'abonnement se
fait **par nom d'événement** (`"auth.user_created"`), jamais par import
de l'objet `RemoteSignal` du service émetteur : `service_order` n'a en
général pas accès au code de `service_auth`, donc ce serait impossible
de toute façon. C'est cette règle — s'abonner à un nom, pas à un objet
Python — qui permet à deux services de communiquer sans se connaître.

### Consommer les événements : le worker

```
python manage.py eventbus_worker
```

Démarre un worker bloquant qui consomme les `event_type` ayant un
`@receiver` local dans ce service, exécute les receivers, acquitte en
cas de succès, retente en cas d'échec puis déplace l'événement en
dead-letter (`{stream}:dlq`) après `MAX_RETRIES` tentatives (backend
Redis). C'est un process à part, à lancer en continu (comme un worker
Celery) — un par service qui a au moins un `@receiver`.

### `RemoteSignal.send()` et les transactions

`send()` publie via `transaction.on_commit()` : si l'appel a lieu dans
une transaction (typiquement un `post_save`), l'événement n'est envoyé
qu'après le commit effectif — jamais pour une ligne dont l'écriture a
finalement été annulée par un rollback. Hors transaction, il part
immédiatement.

**Conséquence en tests** : avec `pytest.mark.django_db` seul (rollback
implicite en fin de test), le callback ne se déclenche jamais — utilisez
`pytest.mark.django_db(transaction=True)` (ou la fixture pytest-django
`django_capture_on_commit_callbacks`) pour tout test qui vérifie qu'un
événement a bien été émis.

### Ce que la librairie garantit — et ce qu'elle ne garantit pas

Le bus est **at-least-once** : un événement peut être livré plusieurs
fois à un `@receiver` (redélivrance après un `fail()`, ou après un crash
du worker avant l'`ack`). **Écrivez des receivers idempotents** (ex:
`get_or_create` plutôt que `create`, ou une clé unique sur
`envelope.event_id`).

`transaction.on_commit()` évite les événements "fantômes" (publiés pour
une donnée jamais committée) mais ne protège pas d'une panne du broker
*au moment précis du commit* : dans ce cas l'écriture DB reste committée
mais la publication échoue et remonte comme une erreur post-commit. Pour
une garantie zéro-perte plus forte, la solution correcte est un pattern
*transactional outbox* (table locale + relais séparé) — hors périmètre
de cette version.

## 2. Lire une donnée détenue par un autre service (`RemoteForeignKey`)

### Le problème, concrètement

`service_order` a besoin d'afficher l'email du client d'une commande.
L'utilisateur vit dans `service_auth`. Sans cette librairie, il faudrait
écrire un client HTTP, connaître l'URL de `service_auth`, gérer le cache
et les pannes réseau à la main, et refaire tout ça pour chaque
ressource. `RemoteForeignKey` fait tout ça à partir d'une déclaration
sur le modèle, comme une `ForeignKey` classique le ferait pour une
relation locale.

### Configurer où sont les autres services

```python
REMOTE_DATA = {
    "SERVICE_REGISTRY": {
        "service_auth": {
            "http": {"base_url": "http://service-auth:8000/api", "timeout": 3},
            "grpc": {"target": "service-auth:50051", "timeout": 3},
        },
    },
    "DEFAULT_TRANSPORT": "http",  # ou "grpc" — voir la section 3
    "DEFAULT_TTL": 60,            # durée de cache en secondes
}
```

**C'est le seul endroit du projet où l'URL de `service_auth` apparaît.**
Le code applicatif (ci-dessous) ne la connaît jamais.

### Déclarer le champ

```python
# orders/models.py
from django_event_bus.remote import RemoteForeignKey

class Order(models.Model):
    user_id = RemoteForeignKey(
        service="service_auth",   # clé dans SERVICE_REGISTRY
        resource="users",         # doit correspondre au `resource=` exposé (section 3)
        invalidate_on=["auth.user_updated"],  # voir "Invalidation" plus bas
    )

order.user.email   # -> cache Django, sinon HTTP/gRPC vers service_auth
```

- `user_id` est une colonne entière ordinaire : `makemigrations`/`migrate`
  fonctionnent normalement, comme pour n'importe quel `IntegerField`.
- `order.user` — le nom est dérivé de `user_id` en retirant le suffixe
  `_id`, exactement comme le ferait une `ForeignKey` Django. Si votre
  champ ne se termine pas par `_id`, l'accesseur devient
  `{nom_du_champ}_remote` (ou donnez `accessor_name=...` explicitement).
- L'accès à `order.user` **résout paresseusement** : d'abord le cache
  Django (`REMOTE_DATA["CACHE_ALIAS"]`, `locmem` par défaut, un vrai
  cache Redis en prod si vous configurez `CACHES`), puis, si absent ou
  expiré, le transport configuré.
- Ressource absente côté service source (404) → `order.user` vaut
  `None`, comme une `ForeignKey` nullable non résolue. Service
  injoignable (panne réseau, timeout) → lève
  `RemoteServiceUnavailableError` : c'est volontaire, une donnée
  indisponible doit être visible par votre code, pas masquée derrière
  un `None` ambigu.

> **Piège classique : le cache doit être partagé entre process.**
> Sans `CACHES` explicite, Django utilise `locmem` — un cache **en
> mémoire du process**. Un service tourne presque toujours en plusieurs
> process (le serveur web, `eventbus_worker`, `remote_grpc_server`, un
> `manage.py shell` ponctuel) : avec `locmem`, chacun a sa propre
> mémoire isolée, et l'invalidation faite par `eventbus_worker` (section
> "Invalidation par événement" plus bas) n'a **aucun effet visible** sur
> le cache vu par le serveur web — sans la moindre erreur, juste une
> donnée qui ne se rafraîchit jamais. Utilisez un cache réellement
> partagé, par exemple Redis (Django ≥ 4.0 fournit un backend natif) :
> ```python
> CACHES = {
>     "default": {
>         "BACKEND": "django.core.cache.backends.redis.RedisCache",
>         "LOCATION": "redis://localhost:6379/1",
>     }
> }
> ```
> C'est exactement ce que fait `example/` (voir plus bas) — ce piège y a
> été découvert et corrigé en vérifiant la démo avec des process
> persistants plutôt qu'un `manage.py shell` relancé à chaque étape (qui
> masque le problème : un process neuf a de toute façon un cache froid).

## 3. Exposer ses données (`@expose_resource`)

### Le problème, concrètement

Le point précédent suppose que `service_auth` sait répondre "voici
l'utilisateur numéro 5" par HTTP et par gRPC. Sans mécanisme dédié, il
faudrait écrire à la main une vue Django *et* une fonction de résolution
gRPC, en dupliquant la même liste de champs dans les deux — pénible dès
qu'on expose plus d'une ressource, et rapidement source d'incohérences
(HTTP renvoie un champ que gRPC a oublié, etc.). `@expose_resource`
résout ça avec **une seule déclaration** qui alimente les deux
transports.

### Déclarer une ressource

```python
# accounts/resources.py — découvert automatiquement, comme events.py
from django.contrib.auth.models import User
from django_event_bus.remote import ResourceSerializer, expose_resource

@expose_resource
class UserResourceSerializer(ResourceSerializer):
    class Meta:
        model = User
        resource = "users"  # la clé attendue par RemoteForeignKey(resource=...)
        fields = ["id", "username", "email", "full_name"]

    def get_full_name(self, instance):
        """Champ calculé: n'existe pas sur le modèle, construit à la demande.

        Convention get_<champ>, identique à SerializerMethodField de
        Django REST Framework — familière si vous avez déjà utilisé DRF.
        """
        full_name = f"{instance.first_name} {instance.last_name}".strip()
        return full_name or instance.username
```

C'est tout : cette classe répond maintenant en HTTP et en gRPC, pour
n'importe quel service qui a `service_auth` dans son `SERVICE_REGISTRY`.

### Personnaliser `ResourceSerializer`

| Ce que vous voulez faire | Comment |
|---|---|
| Exposer tous les champs du modèle | `fields = "__all__"` (défaut si `fields` est omis) |
| Exposer une liste précise | `fields = ["id", "email"]` |
| Exposer tout sauf certains champs | `exclude = ["password"]` (incompatible avec `fields` explicite) |
| Ajouter un champ calculé / renommer un champ | une méthode `get_<champ>(self, instance)` — voir `get_full_name` ci-dessus |
| Restreindre la requête (visibilité, `select_related`, ...) | surcharger `get_queryset(cls)` (classmethod) |
| Contrôle total sur la forme de sortie | surcharger `to_representation(self, instance)` — ignore alors `fields`/`get_<champ>` |

```python
@expose_resource
class UserResourceSerializer(ResourceSerializer):
    class Meta:
        model = User
        resource = "users"
        exclude = ["password", "is_superuser"]

    @classmethod
    def get_queryset(cls):
        # Exemple: ne jamais exposer les comptes désactivés.
        return User.objects.filter(is_active=True).select_related(...)
```

Une ressource déjà prise par une autre classe lève
`ImproperlyConfiguredError` (deux serializers ne peuvent pas se
disputer le même nom) ; `Meta.model`/`Meta.resource` manquants lèvent la
même exception, tôt, plutôt qu'une erreur confuse au premier appel.

### Câbler l'HTTP

```python
# service_auth/urls.py
from django.urls import include, path

urlpatterns = [
    path("api/", include("django_event_bus.remote.urls")),
]
```

Une seule ligne, quel que soit le nombre de ressources exposées : elle
sert `GET /api/<resource>/<pk>/` pour toutes, avec 404 propre si la
ressource ou le PK est inconnu.

### Câbler le gRPC

Aucune configuration nécessaire : dès qu'au moins une ressource est
déclarée via `@expose_resource`, `REMOTE_DATA["GRPC_RESOLVER"]` pointe
par défaut vers le résolveur générique de la librairie. Démarrez
simplement le serveur :

```
python manage.py remote_grpc_server --port 50051
```

Le contrat gRPC est volontairement unique et générique
(`GetResource(resource, pk) -> JSON`, voir
`django_event_bus/remote/proto/remote_resource.proto`) : aucun service
n'a besoin d'écrire son propre `.proto`. La donnée est transportée en
JSON plutôt qu'en `google.protobuf.Struct` — `Struct` n'a qu'un type
numérique (`double`) et convertirait silencieusement chaque entier en
flottant (perte de précision au-delà de 2^53) ; le JSON, lui,
distingue `int` et `float`, comme le fait déjà le transport HTTP.

Pour basculer un `RemoteForeignKey` du côté consommateur sur gRPC, sans
rien changer côté fournisseur (même `@expose_resource`) :

```python
REMOTE_DATA = {
    "SERVICE_REGISTRY": {"service_auth": {"grpc": {"target": "service-auth:50051"}}},
    "DEFAULT_TRANSPORT": "grpc",
}
```

### Sécuriser les endpoints exposés

Par défaut, ni `resource_detail` ni le serveur gRPC ne font
d'authentification — voir [SECURITY.md](SECURITY.fr.md) et
[THREAT_MODEL.fr.md](THREAT_MODEL.fr.md) pour le tableau complet (ils
supposent un réseau privé de confiance). Le rate limiting est actif par
défaut ; l'authentification et le TLS sont des couches optionnelles,
utilisables indépendamment :

```python
# Côté fournisseur (service_auth)
REMOTE_DATA = {
    "AUTH_TOKEN": "un-secret-partage",              # HTTP: 401 / gRPC: UNAUTHENTICATED sans lui
    "GRPC_SERVER_CREDENTIALS": "accounts.tls.build_server_credentials",  # -> grpc.ServerCredentials
    "REQUIRE_TLS": True,                            # échoue plutôt que retomber en clair
    # "RATE_LIMIT": {"LIMIT": 300, "WINDOW_SECONDS": 60},  # la valeur par défaut ; None désactive
    # "MAX_RESPONSE_BYTES": 2_000_000,                     # la valeur par défaut
}

# Côté consommateur (service_order)
REMOTE_DATA = {
    "SERVICE_REGISTRY": {
        "service_auth": {
            "http": {"base_url": "https://...", "auth_token": "un-secret-partage"},
            "grpc": {"target": "...", "auth_token": "un-secret-partage", "credentials": channel_creds},
        },
    },
}
```

`AUTH_TOKEN` est un raccourci vers `StaticTokenAuthBackend` — un seul
secret partagé pour tous les appelants. Pour une identité par appelant à
durée de vie courte et auto-expirante, utilisez plutôt
`remote.auth.JWTAuthBackend` (nécessite
`pip install django-event-bus[jwt]`) via `REMOTE_DATA["AUTH_BACKEND"]`
(chemin pointé vers une instance) :

```python
# accounts/auth_backend.py
from django_event_bus.remote.auth import JWTAuthBackend

backend = JWTAuthBackend(settings.JWT_SIGNING_KEY, audience="service_auth")

# settings.py
REMOTE_DATA = {"AUTH_BACKEND": "accounts.auth_backend.backend"}
```

Pour un rate limiting plus fin que la valeur par défaut, enveloppez
`resource_detail` vous-même dans votre propre `urls.py` (ex: avec
`django-ratelimit`) plutôt que d'inclure `django_event_bus.remote.urls`
tel quel, et/ou passez votre propre `grpc.ServerInterceptor` via
`serve(..., interceptors=[...])` dans `manage.py remote_grpc_server` —
il s'exécute après le rate limiter et le contrôle d'authentification
intégrés.

### Invalidation par événement

```python
user_id = RemoteForeignKey(
    service="service_auth",
    resource="users",
    invalidate_on=["auth.user_updated"],
)
```

Réutilise le bus d'événements (partie 1) plutôt que d'inventer un second
mécanisme : quand `service_auth` publie l'un des `event_type` listés
(avec le PK dans `payload["id"]` — la même convention que
`RemoteSignal.send(payload={"id": ...})` déjà utilisée pour les
événements métier), le cache de la ressource concernée est supprimé.
Combiné au TTL (`DEFAULT_TTL`), ça couvre deux formes de fraîcheur : le
TTL absorbe le cas où l'événement d'invalidation serait raté ou en
retard (best effort), l'événement, quand il arrive, invalide
immédiatement sans attendre l'expiration du TTL. **Ça suppose qu'un
worker (`manage.py eventbus_worker`) tourne côté service consommateur**
— sans worker actif, seul le TTL joue.

## Démo à deux services : tout essayer pour de vrai

`example/` contient `service_auth` et `service_order`, et l'échange de
données s'y fait **dans les deux sens** — ce n'est pas qu'un service qui
lit l'autre :

| | expose (fournisseur) | consomme (`RemoteForeignKey`) | événements publiés |
|---|---|---|---|
| `service_auth` | `User` (`accounts/resources.py`, HTTP+gRPC) | `OrderBookmark.order_id` → `service_order` (`accounts/models.py`) | `auth.user_created`/`auth.user_updated` |
| `service_order` | `Order` (`orders/resources.py`, HTTP) | `Order.user_id` → `service_auth` (`orders/models.py`) | `orders.order_created`/`orders.order_updated` |

Chaque service a aussi de vraies pages web, sans shell ni curl
nécessaire : `http://localhost:8001/accounts/` et
`http://localhost:8002/orders/` listent les comptes/commandes existants
et ont un formulaire pour en créer — chaque création redirige vers un
"dashboard" (`.../<pk>/dashboard/`) qui affiche les données locales **et**
la donnée résolue à distance côte à côte, avec un formulaire pour
modifier la valeur locale (déclenche l'événement, donc l'invalidation
côté de l'autre service) et, côté `service_auth`, un formulaire pour
épingler une commande par son id (`accounts/views.py`, `orders/views.py`).

### Option A (recommandée) : tout en une commande avec Docker

```sh
docker compose -f example/docker-compose.yml up -d --build
```

Une seule image (`Dockerfile` à la racine) sert de base à sept
conteneurs : Redis, un `_migrate` jetable par service (applique les
migrations puis s'arrête — les autres attendent sa réussite pour éviter
des migrations concurrentes sur le même fichier SQLite), et les process
`_http`/`_grpc`/`_worker` de chaque service. Rien à lancer à la main.
`docker compose -f example/docker-compose.yml ps` doit montrer six
conteneurs `Up` (les deux `_migrate` se terminent, c'est normal).

Le plus simple : ouvrez `http://localhost:8001/accounts/` et
`http://localhost:8002/orders/` dans un navigateur, créez un compte puis
une commande (référençant son id), et épinglez-la depuis le dashboard du
compte — tout se fait par formulaire, aucune commande à taper.

Alternative en ligne de commande, via `docker compose exec` (un `manage.py shell` normal, dans le conteneur) :

```sh
echo "
from django.contrib.auth.models import User
User.objects.create_user(username='bob', email='bob@example.com', password='x')
" | docker compose -f example/docker-compose.yml exec -T service_auth_http \
    uv run python example/service_auth/manage.py shell

echo "
from orders.models import Order
Order.objects.create(reference='ORD-1', user_id=1)
" | docker compose -f example/docker-compose.yml exec -T service_order_http \
    uv run python example/service_order/manage.py shell

echo "
from django.contrib.auth.models import User
from accounts.models import OrderBookmark
OrderBookmark.objects.create(user=User.objects.get(pk=1), order_id=1)
" | docker compose -f example/docker-compose.yml exec -T service_auth_http \
    uv run python example/service_auth/manage.py shell
```

Puis consultez les deux dashboards :

```sh
curl http://localhost:8002/orders/1/dashboard/      # sens service_order -> service_auth
curl http://localhost:8001/accounts/1/dashboard/    # sens service_auth -> service_order
```

Chacun affiche ses données locales et celles résolues à distance.
Modifiez l'un ou l'autre (même schéma `echo ... | docker compose exec ...
manage.py shell`, `User.objects.get(pk=1).email = "..."; .save()` ou
`Order.objects.get(pk=1).reference = "..."; .save()`) puis rechargez les
deux `curl` : chaque dashboard reflète la valeur à jour, invalidée par
l'événement publié par l'autre service — **sans redémarrer aucun
conteneur**.

Pour arrêter et tout nettoyer : `docker compose -f example/docker-compose.yml down -v`.

### Option B : à la main, pas à pas, pour comprendre chaque brique

```sh
# Terminal 1: Redis
docker compose -f example/docker-compose.yml up -d redis

# Une fois, pour créer les bases sqlite
uv run python example/service_auth/manage.py migrate
uv run python example/service_order/manage.py migrate

# Terminal 2: service_auth répond en HTTP sur :8001
uv run python example/service_auth/manage.py runserver 8001
# Terminal 3: service_auth répond aussi en gRPC sur :50051
uv run python example/service_auth/manage.py remote_grpc_server --port 50051
# Terminal 4: service_auth consomme orders.order_updated
uv run python example/service_auth/manage.py eventbus_worker

# Terminal 5: service_order répond en HTTP sur :8002
uv run python example/service_order/manage.py runserver 8002
# Terminal 6: service_order consomme auth.user_created/user_updated
uv run python example/service_order/manage.py eventbus_worker
```

**Étape A — un événement traverse le bus.** Dans un 7e terminal :

```
uv run python example/service_auth/manage.py shell
>>> from django.contrib.auth.models import User
>>> User.objects.create_user(username="bob", email="bob@example.com", password="x")
```

`service_auth` publie `auth.user_created` ; le worker du terminal 6 le
consomme et persiste un `ReceivedEvent`. `service_order` n'a jamais
importé une seule ligne de code de `service_auth` pour que ça fonctionne.

**Étape B — `RemoteForeignKey` résout via HTTP, dans les deux sens.**

```
uv run python example/service_order/manage.py shell
>>> from orders.models import Order
>>> order = Order.objects.create(reference="ORD-1", user_id=1)
>>> order.user.email
'bob@example.com'
```

```
uv run python example/service_auth/manage.py shell
>>> from django.contrib.auth.models import User
>>> from accounts.models import OrderBookmark
>>> OrderBookmark.objects.create(user=User.objects.get(pk=1), order_id=1)
```

Consultez les deux dashboards dans un navigateur (ou `curl`) :
`http://localhost:8002/orders/1/dashboard/` et
`http://localhost:8001/accounts/1/dashboard/`.

**Étape C — invalidation par événement, dans les deux sens.** Toujours dans un shell `service_auth` :

```
>>> u = User.objects.get(username="bob")
>>> u.email = "bob.nouveau@example.com"
>>> u.save()
```

Et dans un shell `service_order` :

```
>>> order.reference = "ORD-1-v2"
>>> order.save()
```

Chaque `.save()` publie un événement (`auth.user_updated` /
`orders.order_updated`) que le worker de l'*autre* service consomme
pour invalider son cache. **Rechargez les deux dashboards** (`curl` ou
navigateur, sans relancer aucun process) : les deux reflètent
maintenant les valeurs à jour.

**Étape D — le même `order.user` fonctionne en gRPC.** Dans le shell `service_order` :

```
>>> from django.test import override_settings
>>> with override_settings(REMOTE_DATA={
...     "SERVICE_REGISTRY": {"service_auth": {"grpc": {"target": "localhost:50051"}}},
...     "DEFAULT_TRANSPORT": "grpc",
... }):
...     print(order.user.as_dict())
{'id': 1, 'username': 'bob', 'email': 'bob.nouveau@example.com', 'full_name': 'bob'}
```

Même `@expose_resource` côté `service_auth`, transport différent côté
`service_order` — c'est tout ce qu'il fallait changer.

## Tests

```
uv run pytest                       # unitaires (LocMemBroker, FakeTransport, gRPC en mémoire) — sans infra
docker compose -f example/docker-compose.yml up -d redis
uv run pytest -m integration        # contre un vrai Redis
uv run ruff check .                 # PEP 8 / PEP 257 (pydocstyle) / imports / nommage
uv run ruff format --check src tests example
uv run mypy src                     # PEP 484/526 (typage statique)
```

## Régénérer les stubs gRPC

Après modification de `src/django_event_bus/remote/proto/remote_resource.proto` :

```
./scripts/generate_grpc_stubs.sh
```

## Développement

Voir [CONTRIBUTING.fr.md](CONTRIBUTING.fr.md) pour contribuer et
[CHANGELOG.fr.md](CHANGELOG.fr.md) pour l'historique des versions.

## Licence

[MIT](LICENSE)
