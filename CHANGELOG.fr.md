# Changelog

[English](CHANGELOG.md) · Français

Tous les changements notables de ce projet sont documentés ici.

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/),
et ce projet respecte le [Versionnage Sémantique](https://semver.org/lang/fr/).

## [Non publié]

## [1.0.0rc1] - 2026-08-18

### Ajouté

- **Bus d'événements** : `RemoteSignal` (émission) et
  `@receiver(event_type)` (abonnement par nom d'événement, pas par
  import de l'objet Python du service émetteur — tout l'intérêt étant
  que deux services ne connaissent pas le code l'un de l'autre). Les
  fichiers `events.py` sont découverts automatiquement dans chaque app
  installée au démarrage, même mécanisme que `admin.autodiscover()`.
- Deux backends de broker interchangeables via `EVENT_BUS["BACKEND"]` :
  `LocMemBroker` (défaut, en mémoire, sans infra — pour tests/dev) et
  `RedisStreamsBroker` (Redis Streams + consumer groups : durable,
  livraison at-least-once, plusieurs workers du même service peuvent
  partager un groupe, retry automatique puis dead-letter après
  `MAX_RETRIES`, et résilience aux coupures réseau/connexion
  transitoires sur la lecture bloquante).
- `manage.py eventbus_worker` : commande bloquante qui consomme chaque
  `event_type` ayant un `@receiver` local, acquitte en cas de succès,
  retente puis déplace en dead-letter en cas d'échec.
- `RemoteSignal.send()` publie via `transaction.on_commit()` : un
  événement n'est envoyé qu'une fois la transaction englobante
  effectivement committée, jamais pour une ligne dont l'écriture a été
  annulée.
- **`RemoteForeignKey`** : un champ de modèle qui résout la donnée d'un
  service distant à partir d'un PK stocké localement — une colonne
  entière ordinaire (`makemigrations`/`migrate` fonctionnent
  normalement), un accesseur dérivé du nom du champ (`user_id` →
  `user`, comme une `ForeignKey` classique), résolution paresseuse via
  le cache Django puis, en cas d'absence, le transport configuré (HTTP
  ou gRPC). Un 404 côté service source donne `None` ; une panne réseau
  lève `RemoteServiceUnavailableError` plutôt que d'échouer
  silencieusement. `invalidate_on=[...]` réutilise le bus d'événements
  pour supprimer l'entrée de cache concernée dès que le service source
  publie l'un des événements listés.
- **`@expose_resource`** / `ResourceSerializer` : une façon déclarative,
  façon Django REST Framework, d'exposer un modèle à `RemoteForeignKey`
  — `Meta.model`/`Meta.resource`/`fields` (`"__all__"` ou liste
  explicite)/`exclude`, méthodes `get_<champ>` pour les champs calculés
  (convention `SerializerMethodField`), `get_queryset()`/
  `to_representation()` surchargeables pour un contrôle total. Une
  seule déclaration répond à la fois en HTTP
  (`django_event_bus.remote.urls`, un seul `include()`) et en gRPC
  (`REMOTE_DATA["GRPC_RESOLVER"]` pointe par défaut vers le résolveur
  générique construit à partir de ce registre).
- Contrat gRPC générique (`remote/proto/remote_resource.proto`) : un
  unique RPC `GetResource(resource, pk)` pour qu'aucun service n'ait à
  écrire son propre `.proto`. La donnée est transportée en JSON plutôt
  qu'en `google.protobuf.Struct` — `Struct` n'a qu'un type numérique
  `double` et convertirait silencieusement les entiers en flottants
  (perte de précision au-delà de 2^53) ; le JSON préserve `int`/`float`
  comme le fait déjà le transport HTTP. `manage.py remote_grpc_server`
  démarre le serveur côté fournisseur.
- Une démo à deux services (`example/`) exerçant toutes les
  fonctionnalités dans les deux sens (`service_auth` ⇄
  `service_order`), avec de vrais dashboards web, un `Dockerfile` et un
  `docker-compose.yml` qui démarre tout (Redis, migrations, process
  HTTP/gRPC/worker) en une seule commande
  `docker compose up -d --build`.
