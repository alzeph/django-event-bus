# Modèle de menace

[English](THREAT_MODEL.md) · Français

`django-event-bus` est une bibliothèque, pas un service déployé : elle
tourne dans le process de chaque service adoptant, dans sa propre
frontière de confiance. Ce document décrit les actifs qu'elle manipule,
les acteurs considérés, et distingue les risques traités dans le code
de ceux acceptés par conception (et pourquoi) — le raisonnement derrière
les points déjà listés dans [SECURITY.md](SECURITY.fr.md), pas une
redite.

## Périmètre

Dans le périmètre : le code de la bibliothèque elle-même
(`src/django_event_bus/`) — le bus d'événements (broker Redis Streams,
dispatcher), et le volet données distantes (`RemoteForeignKey`,
`@expose_resource`, les transports et serveurs HTTP/gRPC).

Hors périmètre : la sécurité de Redis, de l'application Django qui
embarque la bibliothèque, du réseau/mesh sur lequel tournent les
services, et de la démo `example/` (valeurs par défaut volontairement
non sécurisées pour un usage local — voir son propre `DEBUG = True`,
`SECRET_KEY` en clair).

## Actifs

- **Les payloads d'événements** en transit (Redis Streams) et au repos
  (jusqu'à consommation/troncature) : du JSON arbitraire fourni par le
  service adoptant, potentiellement porteur de données métier.
- **Les données de ressources exposées** : tout ce qu'un
  `ResourceSerializer` met dans `fields` — la bibliothèque ne sait pas
  quelles colonnes sont sensibles.
- **Les secrets partagés / clés de signature** : `AUTH_TOKEN`, une clé
  de signature `JWTAuthBackend`, des clés privées TLS — fournis par le
  service adoptant, jamais générés ni stockés par la bibliothèque
  elle-même.
- **La disponibilité du service** : le worker du bus d'événements, les
  endpoints gRPC/HTTP, la connexion Redis.

## Acteurs

| Acteur | Capacité supposée |
|---|---|
| Un autre service dans `SERVICE_REGISTRY` | De confiance par défaut (voir "Risques acceptés" plus bas) : peut joindre les transports configurés, supposé exécuter du code de la même organisation. |
| Un opérateur avec accès Redis | Peut lire/écrire n'importe quel stream, y compris la dead-letter — voit les payloads d'événements en clair. |
| Un attaquant adjacent au réseau (même VPC/segment, sans identifiants valides) | Peut tenter de joindre `resource_detail`/le port gRPC si l'isolation réseau est mal configurée. L'acteur principal contre lequel se défendent les options auth/TLS/rate-limit de `SECURITY.md`. |
| Un appelant détenant un `AUTH_TOKEN` statique fuité | Obtient le même accès que n'importe quel consommateur légitime des ressources exposées par ce service — le backend à token statique ne peut pas les distinguer (voir "Risques acceptés"). |

## STRIDE, par composant

| Composant | Menace | Mitigation | Risque résiduel |
|---|---|---|---|
| `resource_detail` / `GetResource` gRPC | **Spoofing** — usurpation de l'appelant | `AUTH_BACKEND`/`AUTH_TOKEN` (optionnel), TLS (optionnel, `REQUIRE_TLS` pour l'imposer) | Les deux sont opt-in ; un déploiement mal configuré est non authentifié par conception (hypothèse de confiance réseau documentée) |
| `resource_detail` / `GetResource` gRPC | **Tampering** — requête altérée en transit | TLS (optionnel) | Transport en clair si TLS non configuré |
| Redis Streams | **Tampering** — un opérateur ou un process compromis réécrit des entrées de stream | Aucune (l'auth/ACL propre à Redis relève du service adoptant) | Hors périmètre — le durcissement de Redis est la responsabilité de l'exploitant |
| `resource_detail` / `GetResource` gRPC | **Repudiation** — aucune trace de qui a accédé à quoi | Logger structuré `remote.audit` (accordé/refusé, appelant, pair, ressource, pk) | Le stockage/la rétention des logs relève de l'exploitant ; le backend à token statique ne peut pas attribuer un accès accordé à un appelant précis |
| `ResourceSerializer` / `@expose_resource` | **Information disclosure** — un champ sensible se retrouve dans `fields` | Aucune automatique — `SECURITY.md` documente la responsabilité de revue | La bibliothèque ne peut pas savoir quelles colonnes sont sensibles ; une allowlist "refus par défaut" (`fields`, pas `"__all__"`) est une convention, pas une contrainte imposée |
| Transports HTTP/gRPC (côté consommateur) | **Information disclosure / DoS** — réponse démesurée d'un pair "de confiance" compromis | `MAX_RESPONSE_BYTES` (lecture bornée, par blocs) | Un pair restant sous la limite d'octets peut toujours renvoyer des données trompeuses (mais bien formées) — la confiance dans les données du pair, pas seulement dans leur taille, reste supposée |
| `resource_detail` / `GetResource` gRPC | **Denial of service** — afflux de requêtes | `RATE_LIMIT` (actif par défaut, fenêtre fixe grossière, appuyée sur le cache) | Un afflux distribué (nombreuses adresses/pairs source) n'est pas traité ; c'est une protection anti-abus, pas anti-DDoS |
| Dispatcher / receivers | **Elevation of privilege** — un receiver disposant de plus de confiance que l'événement ne le justifie | Aucune — les receivers tournent avec les pleins privilèges du process du service consommateur | Par conception : le bus d'événements est un pub/sub interne à un seul domaine de confiance, pas un système de plugins bac-à-sable |

## Risques acceptés (par conception)

Ce ne sont pas des manques à corriger en silence — ce sont des
compromis documentés. Signalés comme vulnérabilités, ils seront triés
comme "comportement attendu, documentation clarifiée" plutôt que
"bug", sauf si le signalement montre un moyen de contourner une
mitigation affirmée (ex : contourner `RATE_LIMIT`, forger un JWT sans la
clé, lire une entrée de stream au-delà des garanties de rétention de
`MAXLEN`).

1. **Confiance entre services enregistrés.** Les entrées de
   `SERVICE_REGISTRY` sont supposées être d'autres services de la même
   organisation/du même déploiement. La bibliothèque n'a pas de notion
   de service "semi-confiance" ni d'autorisation par ressource entre
   services — voir `AUTH_BACKEND` pour l'approximation la plus proche
   (un secret partagé ou un token signé), pas un vrai RBAC à moindre
   privilège.
2. **Pas de chiffrement au repos.** Les payloads d'événements résident
   dans les Redis Streams (et le cache Django, pour les `RemoteObject`
   résolus) en JSON en clair. Les chiffrer relève de la responsabilité
   de l'exploitant (TLS Redis, chiffrement disque/volume) si les
   payloads le justifient.
3. **Livraison at-least-once, pas exactly-once.** Un receiver peut
   tourner plus d'une fois pour le même événement (retry après un échec
   partiel, un message pendant repris, ...). Les receivers doivent être
   idempotents — c'est un contrat de correction, documenté dans le
   README, pas une frontière de sécurité, mais un attaquant capable de
   déclencher la répétition d'un événement légitime pourrait exploiter
   un receiver non idempotent.
4. **Le backend d'auth à token statique est un secret partagé, pas une
   identité.** Quiconque le détient est indistinguable de tout autre
   détenteur légitime dans le journal d'audit (`caller="shared-token"`).
   Utilisez `JWTAuthBackend` quand l'attribution par appelant compte.

## Hors périmètre pour cette bibliothèque

- L'authentification/les ACL/le TLS propres à Redis.
- La surface d'attaque propre au service Django adoptant (ses vues, son
  `SECRET_KEY`, son réglage `DEBUG`, ...).
- La sécurité physique/de l'hôte sur lequel tournent les services.
- L'intégrité de la chaîne d'approvisionnement des dépendances en
  dessous de `django-event-bus` lui-même (couverte opérationnellement
  par `pip-audit` en CI et Dependabot, pas par ce document).
