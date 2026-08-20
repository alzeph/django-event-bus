"""Commande ``manage.py remote_grpc_server``.

``manage.py remote_grpc_server`` command.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils.module_loading import import_string

from django_event_bus.remote.auth import resolve_auth_backend
from django_event_bus.remote.grpc_server import serve
from django_event_bus.remote.ratelimit import resolve_rate_limit_config
from django_event_bus.settings import remote_settings


class Command(BaseCommand):
    """Démarre le serveur gRPC exposant les données de ce service aux autres.

    Utilise ``REMOTE_DATA["GRPC_RESOLVER"]`` (chemin pointé vers une
    fonction ``(resource: str, pk: str) -> dict | None``) pour savoir
    comment résoudre une ressource demandée.

    Starts the gRPC server exposing this service's data to the others.

    Uses ``REMOTE_DATA["GRPC_RESOLVER"]`` (dotted path to a
    ``(resource: str, pk: str) -> dict | None`` function) to know how to
    resolve a requested resource.
    """

    help = (
        "Démarre le serveur gRPC générique de récupération de données "
        "distantes (RemoteForeignKey), pour ce service en tant que "
        "source de données."
    )

    def add_arguments(self, parser: Any) -> None:
        """Déclare l'option ``--port`` (défaut: 50051).

        Declares the ``--port`` option (default: 50051).
        """
        parser.add_argument("--port", type=int, default=50051)

    def handle(self, *args: Any, **options: Any) -> None:
        """Résout ``GRPC_RESOLVER`` + auth/TLS/rate-limit, démarre le serveur.

        Resolves ``GRPC_RESOLVER`` + auth/TLS/rate-limit, starts the server.
        """
        resolver_path = remote_settings.GRPC_RESOLVER
        if not resolver_path:
            raise CommandError(
                "REMOTE_DATA['GRPC_RESOLVER'] n'est pas configuré / is not "
                'configured. Ex / e.g.: REMOTE_DATA = {"GRPC_RESOLVER": '
                '"accounts.grpc_resolver.resolve"}'
            )
        resolve = import_string(resolver_path)
        port = options["port"]

        credentials = None
        credentials_path = remote_settings.GRPC_SERVER_CREDENTIALS
        if credentials_path:
            build_credentials = import_string(credentials_path)
            credentials = build_credentials()

        if remote_settings.REQUIRE_TLS and credentials is None:
            raise CommandError(
                "REMOTE_DATA['REQUIRE_TLS'] est actif mais "
                "REMOTE_DATA['GRPC_SERVER_CREDENTIALS'] n'est pas configuré: "
                "refus de démarrer en clair / REMOTE_DATA['REQUIRE_TLS'] is "
                "on but REMOTE_DATA['GRPC_SERVER_CREDENTIALS'] is not "
                "configured: refusing to start in the clear."
            )

        self.stdout.write(self.style.SUCCESS(f"Démarrage sur le port {port}"))
        serve(
            resolve,
            port=port,
            auth_backend=resolve_auth_backend(),
            credentials=credentials,
            rate_limit=resolve_rate_limit_config(remote_settings.RATE_LIMIT),
            max_message_bytes=remote_settings.MAX_RESPONSE_BYTES,
        )
