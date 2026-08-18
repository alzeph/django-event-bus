"""Serveur gRPC réutilisable exposant le RPC générique ``GetResource``.

Reusable gRPC server exposing the generic ``GetResource`` RPC.
"""

from __future__ import annotations

import logging
import signal
import threading
from collections.abc import Callable
from concurrent import futures
from typing import Any

import grpc
from google.protobuf.struct_pb2 import Struct

from .proto import remote_resource_pb2, remote_resource_pb2_grpc

logger = logging.getLogger("django_event_bus.remote.grpc_server")

#: Fonction fournie par le service exposant ses données: renvoie le dict
#: de la ressource demandée, ou ``None`` si elle n'existe pas.
#:
#: Function provided by the service exposing its data: returns the
#: requested resource's dict, or ``None`` if it does not exist.
ResourceResolver = Callable[[str, str], "dict[str, Any] | None"]


class RemoteResourceServicer(remote_resource_pb2_grpc.RemoteResourceServiceServicer):
    """Implémente ``RemoteResourceService`` via un ``ResourceResolver`` fourni.

    Le service source n'a rien à écrire en gRPC: il fournit juste une
    fonction ``(resource, pk) -> dict | None`` (typiquement un
    ``QuerySet.values().get()`` sur le modèle concerné) et cette classe
    se charge de la conversion vers/depuis le protocole.

    Generic implementation of ``RemoteResourceService`` built from a
    ``ResourceResolver``.

    The source service has nothing gRPC-specific to write: it just
    provides a ``(resource, pk) -> dict | None`` function (typically a
    ``QuerySet.values().get()`` on the relevant model) and this class
    handles the conversion to/from the protocol.
    """

    def __init__(self, resolve: ResourceResolver) -> None:
        """Reçoit la fonction de résolution fournie par le service source.

        Receives the resolver function provided by the source service.
        """
        self._resolve = resolve

    def GetResource(  # noqa: N802 - nom imposé par le service gRPC généré / name imposed by generated gRPC service
        self,
        request: remote_resource_pb2.ResourceRequest,
        context: grpc.ServicerContext,
    ) -> remote_resource_pb2.ResourceResponse:
        """Résout la ressource demandée et la sérialise en ``ResourceResponse``.

        Resolves the requested resource and serializes it into a ``ResourceResponse``.
        """
        data = self._resolve(request.resource, request.pk)
        if data is None:
            return remote_resource_pb2.ResourceResponse(found=False)
        struct = Struct()
        struct.update(data)
        return remote_resource_pb2.ResourceResponse(found=True, data=struct)


def serve(
    resolve: ResourceResolver, *, port: int = 50051, max_workers: int = 10
) -> None:
    """Démarre un serveur gRPC bloquant exposant ``GetResource`` via ``resolve``.

    S'arrête proprement sur ``SIGINT``/``SIGTERM`` (même logique que la
    commande ``eventbus_worker`` du bus d'événements).

    Starts a blocking gRPC server exposing ``GetResource`` via ``resolve``.

    Stops cleanly on ``SIGINT``/``SIGTERM`` (same logic as the event
    bus's ``eventbus_worker`` command).
    """
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers))
    remote_resource_pb2_grpc.add_RemoteResourceServiceServicer_to_server(
        RemoteResourceServicer(resolve), server
    )
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    logger.info("Serveur gRPC démarré / gRPC server started sur/on port %s", port)

    stop_event = threading.Event()

    def _handle_stop(signum: int, frame: Any) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)
    stop_event.wait()

    logger.info("Arrêt du serveur gRPC / stopping gRPC server")
    server.stop(grace=5).wait()
