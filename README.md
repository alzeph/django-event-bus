# django-event-bus

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
[Démo à deux services](#démo-à-deux-services-tout-essayer-pour-de-vrai)
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

`example/` contient `service_auth` (fournisseur : publie des événements,
expose l'utilisateur) et `service_order` (consommateur : reçoit les
événements, lit l'utilisateur via `RemoteForeignKey`). Tout ce qui
précède y est mis en œuvre :

- `service_auth/accounts/events.py` — publie `auth.user_created`/`auth.user_updated`
- `service_auth/accounts/resources.py` — expose `User` en HTTP et gRPC
- `service_order/orders/models.py` — `Order.user_id` en `RemoteForeignKey`
- `service_order/orders/events.py` — un `@receiver` qui trace les événements reçus

```sh
# Terminal 1: Redis (le seul composant d'infra nécessaire)
docker compose -f example/docker-compose.yml up -d

# Une fois, pour créer les bases sqlite de la démo
uv run python example/service_auth/manage.py migrate
uv run python example/service_order/manage.py migrate

# Terminal 2: service_auth répond en HTTP sur :8001
uv run python example/service_auth/manage.py runserver 8001

# Terminal 3: service_auth répond aussi en gRPC sur :50051
uv run python example/service_auth/manage.py remote_grpc_server --port 50051

# Terminal 4: service_order consomme les événements du bus
uv run python example/service_order/manage.py eventbus_worker
```

**Étape A — un événement traverse le bus.** Dans un 5e terminal :

```
uv run python example/service_auth/manage.py shell
>>> from django.contrib.auth.models import User
>>> User.objects.create_user(username="bob", email="bob@example.com", password="x")
```

`service_auth` publie `auth.user_created` ; le worker du terminal 4 le
consomme et persiste un `ReceivedEvent` — regardez son terminal, une
ligne apparaît. `service_order` n'a jamais importé une seule ligne de
code de `service_auth` pour que ça fonctionne.

**Étape B — `RemoteForeignKey` résout via HTTP.**

```
uv run python example/service_order/manage.py shell
>>> from orders.models import Order
>>> order = Order.objects.create(reference="ORD-1", user_id=1)
>>> order.user.email          # requête HTTP vers :8001, réponse mise en cache
'bob@example.com'
>>> order.user.email          # cache: aucune requête HTTP cette fois
'bob@example.com'
```

**Étape C — invalidation par événement.** Toujours dans `service_auth` :

```
>>> u = User.objects.get(username="bob")
>>> u.email = "bob.nouveau@example.com"
>>> u.save()
```

Ça publie `auth.user_updated`. Le worker (terminal 4) le consomme et
invalide le cache de cet utilisateur. Dans le shell `service_order` :

```
>>> order.user.email          # le cache a été vidé: nouvelle requête HTTP
'bob.nouveau@example.com'
```

**Étape D — le même `order.user` fonctionne en gRPC.** Toujours dans le
shell `service_order` :

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
docker compose -f example/docker-compose.yml up -d
uv run pytest -m integration        # contre un vrai Redis
uv run ruff check .                 # PEP 8 / PEP 257 (pydocstyle) / imports / nommage
uv run mypy src                     # PEP 484/526 (typage statique)
```

## Régénérer les stubs gRPC

Après modification de `src/django_event_bus/remote/proto/remote_resource.proto` :

```
./scripts/generate_grpc_stubs.sh
```
