# Politique de sécurité

[English](SECURITY.md) · Français

## Signaler une vulnérabilité

Merci de ne pas ouvrir d'issue publique pour une vulnérabilité de
sécurité. Contactez plutôt directement le mainteneur à
[hervecedricyouan@gmail.com](mailto:hervecedricyouan@gmail.com) avec :

- une description du problème et de son impact ;
- les étapes de reproduction ;
- la version de `django-event-bus` concernée.

Une réponse est visée sous 5 jours ouvrés.

## Points d'attention spécifiques à un bus d'événements inter-services

`django-event-bus` fait transiter des données et déclenche du code à
travers des frontières de service et de réseau. Quelques points méritent
une attention particulière :

- **`RemoteForeignKey` et `@expose_resource`** supposent que les
  transports configurés (HTTP, gRPC) joignent des services *de
  confiance* sur un réseau privé/interne. Par défaut, ni la vue HTTP
  générique (`django_event_bus.remote.views.resource_detail`) ni le
  serveur gRPC générique (`django_event_bus.remote.grpc_server`) ne font
  d'authentification ou d'autorisation — ils répondent à n'importe quel
  appelant capable de les joindre. Placez-les derrière votre propre
  frontière réseau (VPC, service mesh, reverse proxy avec authentification)
  plutôt que de les exposer publiquement.
  - **Authentification par secret partagé (optionnelle)** : définissez
    `REMOTE_DATA["AUTH_TOKEN"]` côté service fournisseur pour exiger que
    tout appel HTTP/gRPC présente `Authorization: Bearer <AUTH_TOKEN>`
    (comparaison à temps constant ; 401 côté HTTP, statut
    `UNAUTHENTICATED` côté gRPC sinon). Côté consommateur, définissez
    `auth_token` dans l'entrée `SERVICE_REGISTRY[service]["http"|"grpc"]`
    correspondante : les deux transports l'attachent alors
    automatiquement. C'est un secret partagé, pas une identité par
    appelant ni une autorisation fine — à voir comme une couche
    supplémentaire par-dessus l'isolation réseau, pas un remplacement.
  - **TLS pour gRPC** : `remote.grpc_server.serve()` accepte un argument
    `credentials` (`grpc.ServerCredentials`, ex: via
    `grpc.ssl_server_credentials(...)`) pour servir en TLS plutôt qu'avec
    `add_insecure_port` ; câblez-le depuis
    `manage.py remote_grpc_server` via
    `REMOTE_DATA["GRPC_SERVER_CREDENTIALS"]` (chemin pointé vers un
    callable sans argument qui les construit, ex: depuis des fichiers
    cert/clé ou un gestionnaire de secrets — laissé hors de la librairie
    pour ne pas la lier à un mode de stockage des certificats
    particulier). Côté consommateur, définissez `credentials` (un
    `grpc.ChannelCredentials`) dans `SERVICE_REGISTRY[service]["grpc"]`.
    Le transport HTTP passe déjà par TLS dès que `base_url` est en
    `https://`, comportement standard de `requests`.
  - **Rate limiting** : non intégré, pour ne pas imposer une dépendance
    particulière. Côté HTTP, enveloppez `resource_detail` vous-même dans
    votre propre `urls.py` (ex: avec `django-ratelimit`) plutôt que
    d'inclure `django_event_bus.remote.urls` tel quel. Côté gRPC,
    `serve()` accepte une séquence `interceptors` — passez-y votre propre
    `grpc.ServerInterceptor` de rate limiting ; il s'exécute après le
    contrôle `auth_token`, s'il est configuré.
- **`ResourceSerializer`** n'expose que les champs explicitement listés
  (`fields`) ou non exclus (`exclude`) ; une ressource déclarée avec
  `fields = "__all__"` sur un modèle contenant des colonnes sensibles
  (hash de mot de passe, tokens, ...) les sérialisera. Vérifiez
  `Meta.fields`/`Meta.exclude` sur tout modèle qui n'est pas un pur DTO.
- **Les payloads d'événements** (`RemoteSignal.send(payload=...)`) sont
  sérialisés en JSON et stockés dans des Redis Streams (ou conservés
  dans le process pour `LocMemBroker`). Ne mettez pas de secrets ni
  d'enregistrements sensibles complets dans un payload ; un receiver
  d'un autre service, ou un opérateur inspectant le stream, le verra en
  clair.
- **Les payloads gRPC** sont transportés en chaînes JSON plutôt qu'en
  `google.protobuf.Struct` (voir le README) spécifiquement pour
  préserver la précision numérique — ceci n'a pas d'implication de
  sécurité en soi, mais signifie qu'un payload JSON malformé ou trop
  volumineux venant d'un pair gRPC non fiable est analysé par le module
  standard `json` ; gardez les endpoints gRPC joignables uniquement
  depuis des services de confiance, comme indiqué ci-dessus.
- Un bug faisant fuiter une donnée vers le mauvais service ou le
  mauvais tenant, via un receiver, un `RemoteForeignKey` résolu ou une
  ressource exposée, est une vulnérabilité de sévérité élevée et doit
  être signalé comme telle, pas comme un bug fonctionnel classique.
