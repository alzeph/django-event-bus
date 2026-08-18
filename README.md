# django-event-bus

Bus d'événements inter-services pour architectures microservices Django.
Chaque service (`service_auth`, `service_order`, ...) installe cette
librairie, déclare son nom et son broker dans ses settings, et peut
émettre/recevoir des événements sans configurer Redis/Kafka à la main ni
connaître le code ou l'URL des autres services.

## Installation & configuration

```python
INSTALLED_APPS = [
    ...,
    "django_event_bus",
]

EVENT_BUS = {
    "SERVICE_NAME": "service_auth",
    "BACKEND": "django_event_bus.brokers.redis_streams.RedisStreamsBroker",
    "OPTIONS": {"URL": "redis://localhost:6379/0"},
}
```

Changer de broker (Redis, puis un futur Kafka) se fait uniquement en
changeant `BACKEND`/`OPTIONS` — aucun code applicatif à toucher. Le
backend par défaut, `django_event_bus.brokers.locmem.LocMemBroker`, ne
nécessite aucune infra (utile en tests/dev).

## Émettre un événement

```python
# accounts/events.py
from django_event_bus import RemoteSignal

user_created = RemoteSignal("auth.user_created")
user_created.send(payload={"id": user.id, "email": user.email})
```

## Recevoir un événement (dans un autre service)

```python
# orders/events.py
from django_event_bus import receiver

@receiver("auth.user_created")
def on_user_created(payload, envelope, **kwargs):
    ...
```

Tout fichier `events.py` d'une app installée est découvert automatiquement
au démarrage (même mécanisme que `admin.autodiscover()`). L'abonnement se
fait par nom d'événement (`"auth.user_created"`), pas par import du code
du service émetteur.

### `RemoteSignal.send()` et les transactions

`send()` publie via `transaction.on_commit()`: si l'appel a lieu dans une
transaction (ex: un `post_save`), l'événement n'est envoyé qu'après le
commit effectif — jamais pour une ligne dont l'écriture a finalement été
annulée. Hors transaction, il part immédiatement. Conséquence en tests:
avec `pytest.mark.django_db` seul (rollback implicite en fin de test),
le callback ne se déclenche jamais — utilisez
`pytest.mark.django_db(transaction=True)` (ou la fixture pytest-django
`django_capture_on_commit_callbacks`) pour les tests qui vérifient qu'un
événement a bien été émis.

### Ce que la librairie garantit — et ce qu'elle ne garantit pas

Le bus est **at-least-once**: un événement peut être livré plusieurs fois
à un `@receiver` (redélivrance après un `fail()`, ou après un crash du
worker avant l'`ack`). Écrivez des receivers idempotents (ex: `get_or_create`
plutôt que `create`, clé unique sur `envelope.event_id`, ...).
`transaction.on_commit()` évite les événements "fantômes" (publiés pour
une donnée jamais committée) mais ne protège pas d'une panne du broker
*au moment du commit*: dans ce cas l'écriture DB reste committée mais la
publication échoue et remonte comme une erreur post-commit. Pour une
garantie zéro-perte plus forte, la solution correcte est un pattern
*transactional outbox* (table locale + relais séparé) — hors périmètre
de cette version.

## Consommer les événements

```
python manage.py eventbus_worker
```

Démarre un worker bloquant qui consomme les `event_type` ayant un
`@receiver` local, acquitte en cas de succès, retente en cas d'échec puis
déplace en dead-letter (`{stream}:dlq`) après `MAX_RETRIES` tentatives.

## Démo à deux services

`example/` contient `service_auth` et `service_order`, deux mini-projets
Django qui communiquent réellement via le bus (voir `docs` du dépôt ou le
code de `example/service_auth/accounts/events.py` et
`example/service_order/orders/events.py`).

```
docker compose -f example/docker-compose.yml up -d   # Redis
uv run python example/service_auth/manage.py migrate
uv run python example/service_order/manage.py migrate
uv run python example/service_order/manage.py eventbus_worker   # terminal 1
uv run python example/service_auth/manage.py shell               # terminal 2
>>> from django.contrib.auth.models import User
>>> User.objects.create_user(username="bob", email="bob@example.com", password="x")
```

`service_order` reçoit l'événement et persiste un `ReceivedEvent` sans
jamais importer le code de `service_auth`.

## Tests

```
uv run pytest                       # unitaires (LocMemBroker, pas d'infra)
docker compose -f example/docker-compose.yml up -d
uv run pytest -m integration        # contre un vrai Redis
```
