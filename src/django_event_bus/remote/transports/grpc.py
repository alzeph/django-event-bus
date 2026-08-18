"""Transport gRPC: RPC générique ``GetResource(resource, pk)``.

gRPC transport: generic ``GetResource(resource, pk)`` RPC.
"""

from __future__ import annotations

import json
import threading
from typing import Any

import grpc

from ...exceptions import RemoteServiceUnavailableError
from ..proto import remote_resource_pb2, remote_resource_pb2_grpc
from .base import BaseTransport
from .utils import registry_entry


class GRPCTransport(BaseTransport):
    """Récupère une ressource distante via le RPC générique ``GetResource``.

    Le service source doit exposer le service gRPC
    ``RemoteResourceService`` défini dans ``remote/proto/remote_resource.proto``
    (voir ``remote.grpc_server.RemoteResourceServicer`` pour l'implémenter
    facilement). Un canal gRPC est ouvert et réutilisé par service
    (``target`` venant de
    ``REMOTE_DATA["SERVICE_REGISTRY"][service]["grpc"]``).

    Fetches a remote resource via the generic ``GetResource`` RPC.

    The source service must expose the ``RemoteResourceService`` gRPC
    service defined in ``remote/proto/remote_resource.proto`` (see
    ``remote.grpc_server.RemoteResourceServicer`` to implement it
    easily). One gRPC channel is opened and reused per service (``target``
    coming from
    ``REMOTE_DATA["SERVICE_REGISTRY"][service]["grpc"]``).
    """

    def __init__(self) -> None:
        """Initialise le cache de canaux, vide au départ.

        Initializes the (initially empty) channel cache.
        """
        self._channels: dict[str, grpc.Channel] = {}
        self._lock = threading.Lock()

    def _channel(self, service: str, target: str) -> grpc.Channel:
        """Renvoie le canal du service, en le créant et le mettant en cache si besoin.

        Returns the service's channel, creating and caching it if needed.
        """
        channel = self._channels.get(service)
        if channel is not None:
            return channel
        with self._lock:
            channel = self._channels.get(service)
            if channel is None:
                channel = grpc.insecure_channel(target)
                self._channels[service] = channel
        return channel

    def fetch(self, *, service: str, resource: str, pk: Any) -> dict[str, Any] | None:
        """Appelle ``GetResource`` et convertit la réponse en dict, ``None`` si absent.

        Calls ``GetResource`` and converts the response to a dict, ``None`` if absent.
        """
        config = registry_entry(service, "grpc")
        channel = self._channel(service, config["target"])
        stub = remote_resource_pb2_grpc.RemoteResourceServiceStub(channel)
        request = remote_resource_pb2.ResourceRequest(resource=resource, pk=str(pk))

        try:
            response = stub.GetResource(request, timeout=config.get("timeout", 3))
        except grpc.RpcError as exc:
            raise RemoteServiceUnavailableError(
                f"Appel gRPC vers '{service}' impossible / failed: {exc}"
            ) from exc

        if not response.found:
            return None
        # JSON, pas google.protobuf.Struct: Struct force tout nombre en
        # double et convertirait silencieusement un entier en flottant
        # (perte de précision au-delà de 2^53) — voir remote_resource.proto.
        return json.loads(response.data_json)

    def close(self) -> None:
        """Ferme tous les canaux ouverts.

        Closes all open channels.
        """
        with self._lock:
            for channel in self._channels.values():
                channel.close()
            self._channels.clear()
