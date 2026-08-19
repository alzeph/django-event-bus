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

## Délai de traitement visé

Une fois un signalement confirmé comme une vraie vulnérabilité, les
objectifs de réponse et de correction dépendent de la sévérité
(alignement approximatif sur CVSS) :

| Sévérité | Exemple | Réponse initiale | Correctif ou mitigation publiés |
|---|---|---|---|
| Critique | Exécution de code distante non authentifiée, exfiltration massive de données inter-services | 24h | 72h |
| Élevée | Contournement d'authentification sur `resource_detail`/gRPC, fuite de données inter-tenant (voir plus bas) | 2 jours ouvrés | 7 jours |
| Moyenne | Confusion de privilège sous une configuration spécifique, DoS nécessitant un accès privilégié | 5 jours ouvrés | 30 jours |
| Faible | Suggestion de durcissement, manque de défense en profondeur sans chemin d'exploitation direct | Best effort | Prochaine version mineure |

Ce sont des objectifs, pas des engagements contractuels — projet
open-source à mainteneur unique. Un correctif peut sortir en version
patch, ou sous forme de mitigation documentée quand un correctif de
code n'est pas la bonne réponse (ex : "placez ceci derrière votre VPN",
déjà le cas pour plusieurs points ci-dessous).

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
  - **Authentification, pluggable** : `django_event_bus.remote.auth`
    définit `BaseAuthBackend` ; le service fournisseur en choisit un via
    `REMOTE_DATA["AUTH_BACKEND"]` (chemin pointé vers une instance) ou le
    raccourci `REMOTE_DATA["AUTH_TOKEN"]`. Deux backends fournis :
    - `StaticTokenAuthBackend` (ce que construit `AUTH_TOKEN`) : un seul
      secret partagé pour tous les appelants, `Authorization: Bearer
      <token>`, comparaison à temps constant. Pas d'identité par
      appelant, pas d'expiration — le secret doit être tourné
      manuellement, et une fuite donne accès à tout ce que le service
      expose.
    - `JWTAuthBackend` (nécessite `pip install django-event-bus[jwt]`) :
      vérifie un JWT signé et à courte durée de vie par appelant (`exp`
      obligatoire), exposant le `sub` (ou `iss`) du token comme identité
      d'appelant pour le journal d'audit. À préférer à un token statique
      quand les appelants doivent être distinguables et les secrets
      expirer d'eux-mêmes.
    Côté consommateur, HTTP lit `auth_token` dans
    `SERVICE_REGISTRY[service]["http"]` et gRPC dans
    `SERVICE_REGISTRY[service]["grpc"]` ; les deux attachent
    automatiquement l'en-tête/la métadonnée. Chaque backend reste une
    couche supplémentaire par-dessus l'isolation réseau, pas un
    remplacement.
  - **TLS, et une option pour l'imposer** : `remote.grpc_server.serve()`
    accepte un argument `credentials` (`grpc.ServerCredentials`, ex: via
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
    `https://`, comportement standard de `requests`. Définissez
    `REMOTE_DATA["REQUIRE_TLS"] = True` pour échouer plutôt que de
    retomber silencieusement en clair : le transport HTTP refuse alors
    un `base_url` non-`https://`, le transport gRPC refuse un service
    sans `credentials`, et `manage.py remote_grpc_server` refuse de
    démarrer sans `GRPC_SERVER_CREDENTIALS`.
  - **Rate limiting, actif par défaut** : `REMOTE_DATA["RATE_LIMIT"]`
    (défaut `{"LIMIT": 300, "WINDOW_SECONDS": 60}`, `None` désactive)
    limite `resource_detail` par `REMOTE_ADDR` de l'appelant et le
    serveur gRPC générique par adresse de pair, via le même cache Django
    que les données distantes en cache — une fenêtre fixe grossière,
    suffisante contre l'abus et les tentatives répétées de devinette de
    secret, pas une garantie de débit précise. Pour plus de finesse, la
    séquence `interceptors` de `serve()` accepte toujours votre propre
    `grpc.ServerInterceptor`, appliqué après le rate limiter et le
    contrôle d'authentification intégrés.
  - **Limites de taille de réponse** : `REMOTE_DATA["MAX_RESPONSE_BYTES"]`
    (défaut 2 Mo) borne la quantité lue d'une réponse HTTP/gRPC distante
    par les transports consommateurs avant d'abandonner
    (`RemoteServiceUnavailableError`) — protège un consommateur contre un
    pair "de confiance" compromis ou mal configuré renvoyant un corps
    démesuré. Surchargeable par service via
    `SERVICE_REGISTRY[service]["http"|"grpc"]["max_response_bytes"]`.
  - **Journal d'audit** : chaque décision d'accès (accordée ou refusée)
    sur `resource_detail` et le serveur gRPC générique est journalisée
    via le logger `django_event_bus.remote.audit` (champs structurés
    `extra` : transport, ressource, pk, appelant, pair, accordé, raison)
    — routable ou filtrable indépendamment des logs applicatifs.
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

Voir [THREAT_MODEL.fr.md](THREAT_MODEL.fr.md) pour le tableau complet :
frontières de confiance, actifs et attaquants considérés, et quels
risques sont acceptés par conception plutôt que traités dans le code.
