"""Commande ``manage.py remote_grpc_server``.

``manage.py remote_grpc_server`` command.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils.module_loading import import_string

from django_event_bus.remote.grpc_server import serve
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
        """Résout ``GRPC_RESOLVER`` puis démarre le serveur bloquant.

        Resolves ``GRPC_RESOLVER`` then starts the blocking server.
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
        self.stdout.write(self.style.SUCCESS(f"Démarrage sur le port {port}"))
        serve(resolve, port=port)
