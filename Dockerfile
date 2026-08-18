# Image unique partagée par tous les process de la démo (service_auth
# et service_order, HTTP/gRPC/worker): ils dépendent tous du même
# environnement Python (django_event_bus en editable install + Django +
# redis + grpcio). Seule la commande lancée diffère, voir
# example/docker-compose.yml.
FROM python:3.13-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

# Couche de dépendances séparée du code applicatif: rebuild plus rapide
# quand seul example/ change.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-install-project
COPY . .
RUN uv sync --frozen
