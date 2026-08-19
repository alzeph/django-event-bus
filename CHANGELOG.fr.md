# Changelog

[English](CHANGELOG.md) · Français

Tous les changements notables de ce projet sont documentés ici.

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/),
et ce projet respecte le [Versionnage Sémantique](https://semver.org/lang/fr/).

## [Non publié]

### Ajouté

- **Authentification pluggable** : `django_event_bus.remote.auth` avec
  `BaseAuthBackend`, `StaticTokenAuthBackend` (ce que construit
  `AUTH_TOKEN`), et `JWTAuthBackend` (identité par appelant, tokens
  signés à courte durée de vie — nécessite
  `pip install django-event-bus[jwt]`), sélectionné via
  `REMOTE_DATA["AUTH_BACKEND"]`.
- **Rate limiting actif par défaut** : `REMOTE_DATA["RATE_LIMIT"]`
  (défaut `{"LIMIT": 300, "WINDOW_SECONDS": 60}`) limite
  `resource_detail` et le serveur gRPC générique par adresse/pair
  appelant, appuyé sur le cache ; `None` désactive.
- **Limites de taille de réponse** :
  `REMOTE_DATA["MAX_RESPONSE_BYTES"]` (défaut 2 Mo) borne la quantité
  lue d'une réponse distante par les transports consommateurs
  HTTP/gRPC, surchargeable par service.
- **`REMOTE_DATA["REQUIRE_TLS"]`** : échoue plutôt que de retomber
  silencieusement en HTTP/gRPC non chiffré quand actif.
- **Journal d'audit structuré** : chaque décision d'accès sur
  `resource_detail`/le serveur gRPC est journalisée via le logger
  `django_event_bus.remote.audit`.
- `THREAT_MODEL.md` : frontières de confiance, actifs, STRIDE par
  composant, et risques acceptés par conception. `SECURITY.md` a gagné
  un tableau de délai de traitement visé.
- Gouvernance CI/CD : alertes de vulnérabilité et correctifs de
  sécurité automatiques Dependabot activés côté GitHub ; utilisateur
  non-root dans le `Dockerfile` de démo.

## [1.0.0rc2] - 2026-08-19

### Ajouté

- **Authentification par secret partagé (optionnelle)** :
  `REMOTE_DATA["AUTH_TOKEN"]`, vérifié par `resource_detail` (401 si
  absent/incorrect) et un nouvel intercepteur gRPC (`UNAUTHENTICATED`) ;
  les transports HTTP et gRPC l'attachent automatiquement depuis
  `auth_token` dans l'entrée `SERVICE_REGISTRY` correspondante.
- **TLS pour gRPC** : `remote.grpc_server.serve()` accepte `credentials`
  (`grpc.ServerCredentials`, servi via `add_secure_port`), câblé depuis
  `manage.py remote_grpc_server` via
  `REMOTE_DATA["GRPC_SERVER_CREDENTIALS"]` ; `GRPCTransport` ouvre un
  canal chiffré quand `credentials` est défini dans `SERVICE_REGISTRY`.
- `serve()` accepte une séquence `interceptors`, pour brancher un rate
  limiter gRPC maison (ou tout autre intercepteur) sans forker le
  serveur.
- `resource_detail` restreint désormais explicitement la méthode HTTP à
  `GET` (`@require_GET`).
- `expose_resource` détecte désormais au chargement un champ relation
  (`ForeignKey`) listé sans méthode `get_<champ>`, au lieu d'un
  `TypeError` tardif à l'encodage JSON lors de la première requête.
- `RedisStreamsBroker` accepte une option `MAXLEN` pour borner la
  longueur des streams métier et de dead-letter (`XADD ... MAXLEN ~`).
- CI : un job `security` (`pip-audit`, informatif — non bloquant pour
  `build`) et un workflow CodeQL dédié pour Python.

### Corrigé

- `HTTPTransport`/`GRPCTransport` : un corps de réponse JSON invalide
  lève désormais `RemoteServiceUnavailableError`, comme les autres
  réponses injoignables/en erreur, au lieu d'une exception de décodage
  non gérée.
- `RedisStreamsBroker` : recréer un consumer group perdu suite à une
  erreur `NOGROUP` (suppression manuelle, erreur d'exploitation) ne
  rejoue plus tout l'historique du stream — reprend uniquement les
  nouveaux messages.
- `ResourceSerializer.to_representation` : exposer un champ relation
  sans méthode `get_<champ>` lève désormais une `ImproperlyConfiguredError`
  explicite au lieu d'un `TypeError` à l'encodage JSON.
- `dispatcher.dispatch` : un échec partiel des receivers journalise
  désormais que la ré-émission relancera tous les receivers de
  l'événement, y compris ceux ayant déjà réussi.

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
