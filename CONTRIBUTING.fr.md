# Contribuer à django-event-bus

[English](CONTRIBUTING.md) · Français

Merci de vouloir contribuer ! Ce guide décrit comment installer
l'environnement de développement et ce qui est attendu pour une pull
request.

## Installation

Le projet utilise [uv](https://docs.astral.sh/uv/) pour la gestion des
dépendances et de l'environnement virtuel.

```bash
uv sync --group dev
```

## Vérifications avant d'ouvrir une PR

```bash
uv run ruff check .
uv run ruff format --check src tests example
uv run mypy src
uv run pytest --cov=django_event_bus --cov-report=term-missing

# Nécessite un Redis en cours d'exécution (docker compose -f example/docker-compose.yml up -d redis):
uv run pytest -m integration
```

Ces mêmes vérifications tournent en CI (`.github/workflows/ci.yml`) et
doivent toutes passer pour qu'une PR soit mergeable :

- **ruff** : lint (PEP 8, PEP 257/pydocstyle, ordre des imports,
  nommage) et formatage.
- **mypy** (avec `django-stubs`) : le typage doit rester précis sur
  tout `src/`.
- **pytest**, contre Django 4.2/5.0/5.1/5.2/6.0/6.1 (SQLite). Les tests
  unitaires tournent sans aucun service externe (`LocMemBroker`, un
  `FakeTransport`, un serveur gRPC en mémoire) ; un job séparé exécute
  la suite `-m integration` contre un vrai conteneur de service Redis.

Si `pre-commit` est installé (`uv run pre-commit install`), ruff et
mypy tournent automatiquement avant chaque commit.

## Compatibilité

`django-event-bus` cible **Python 3.13+** et **Django 4.2+** (LTS
actuelle et versions suivantes). Toute PR doit rester compatible avec
ces versions minimales.

## Style de code

- Pas de commentaire qui explique le *quoi* (le code doit être lisible
  par lui-même) — seulement le *pourquoi* quand ce n'est pas évident
  (une contrainte cachée, un invariant subtil, un contournement pour un
  bug précis).
- Pas de commentaire qui narre le processus d'écriture ("nouveau",
  "déjà en place", "contrairement à une version précédente...") — un
  commentaire décrit le code tel qu'il est, pas son historique.
- Pas d'abstraction ni de fonctionnalité ajoutée au-delà de ce qu'exige
  un changement. Un broker, un transport, ou un serializer de ressource
  ne gagne une nouvelle option que lorsqu'un vrai cas d'usage l'exige.
- Les docstrings des modules/classes/fonctions publics sont bilingues :
  un paragraphe en français, puis sa traduction anglaise, dans cet
  ordre (voir n'importe quel fichier sous `src/django_event_bus/` pour
  la convention). Les commentaires inline restent en français, sauf
  quand ils expliquent un choix technique vraiment non évident.
- Tout nouveau broker/transport doit implémenter entièrement
  l'interface `BaseBroker`/`BaseTransport` (`brokers/base.py`,
  `remote/transports/base.py`) et être résilient aux coupures réseau
  transitoires comme l'est `RedisStreamsBroker` (voir sa docstring) :
  un worker ou une résolution `RemoteForeignKey` ne doit pas planter
  sur un incident réseau passager.

## Commits et PR

- Un message de commit clair qui explique le *pourquoi* du changement.
- Une PR = un sujet. Préférez plusieurs petites PR à une seule PR
  fourre-tout.
- Décrivez ce qui change et comment c'est testé dans la description de
  la PR.
- Mettez à jour `CHANGELOG.md` (et `CHANGELOG.fr.md`) si le changement
  affecte l'API publique.

## Politique de compatibilité et de dépréciation

`django-event-bus` suit le [Versionnage Sémantique](https://semver.org/lang/fr/).
Le projet est actuellement en phase de *release candidate* (`1.0.0rcN`) :
l'API est considérée comme figée mais n'a pas encore été éprouvée par un
usage réel hors de ce dépôt — des changements incompatibles restent
possibles entre deux release candidates si un défaut de conception est
découvert, mais sont évités autant que possible.

À partir de `1.0.0` :

- une **majeure** (`X.0.0`) peut casser la compatibilité ;
- une **mineure** (`1.X.0`) ajoute des fonctionnalités sans rien casser ;
- un **patch** (`1.0.X`) ne contient que des corrections de bugs.

Après `1.0.0`, toute API publique dépréciée continue de fonctionner et
lève un `DeprecationWarning` explicite pendant au moins une version
mineure complète avant d'être retirée dans une majeure suivante.

## Signaler un bug ou proposer une fonctionnalité

Ouvrez une [issue](https://github.com/alzeph/django-event-bus/issues) en
utilisant le modèle approprié. Pour une vulnérabilité de sécurité, voir
[SECURITY.fr.md](SECURITY.fr.md) plutôt qu'une issue publique.
