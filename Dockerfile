# Image unique partagée par tous les process de la démo (service_auth
# et service_order, HTTP/gRPC/worker): ils dépendent tous du même
# environnement Python (django_event_bus en editable install + Django +
# redis + grpcio). Seule la commande lancée diffère, voir
# example/docker-compose.yml.
FROM python:3.14-slim

RUN pip install --no-cache-dir uv

# Utilisateur non-root: limite l'impact d'une éventuelle compromission
# du process applicatif à l'intérieur du conteneur (pas de privilège
# root superflu à l'exécution). `uv sync` tourne ci-dessous sous cet
# utilisateur dès le départ plutôt qu'un `chown -R` a posteriori: `uv`
# télécharge son propre interpréteur managé sous le HOME de l'utilisateur
# courant (``~/.local/share/uv/python``) — exécuté en root, ce chemin
# finit sous /root, illisible pour `app` ensuite (permission denied au
# démarrage du conteneur).
#
# /data: point de montage du volume nommé SQLite (voir
# example/docker-compose.yml) — créé et cédé à `app` ici pour que le
# volume nommé hérite de ces permissions dès sa première création.
#
# Non-root user: limits the blast radius of a potential application
# process compromise inside the container (no superfluous root
# privilege at runtime). `uv sync` runs as this user from the start
# below rather than a `chown -R` afterward: `uv` downloads its own
# managed interpreter under the current user's HOME
# (``~/.local/share/uv/python``) — run as root, that path ends up under
# /root, unreadable by `app` afterward (permission denied at container
# startup).
#
# /data: named SQLite volume mount point (see
# example/docker-compose.yml) — created and handed to `app` here so the
# named volume inherits these permissions the first time it's created.
RUN groupadd --system app \
    && useradd --system --gid app --create-home app \
    && mkdir -p /data /app \
    && chown app:app /data /app

WORKDIR /app
USER app

# Couche de dépendances séparée du code applicatif: rebuild plus rapide
# quand seul example/ change.
COPY --chown=app:app pyproject.toml uv.lock README.md ./
COPY --chown=app:app src ./src
RUN uv sync --frozen --no-install-project
COPY --chown=app:app . .
RUN uv sync --frozen
