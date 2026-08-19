"""Transport gRPC: RPC générique ``GetResource(resource, pk)``.

gRPC transport: generic ``GetResource(resource, pk)`` RPC.
"""

from __future__ import annotations

import json
import threading
from typing import Any

import grpc

from ...exceptions import RemoteServiceMisconfiguredError, RemoteServiceUnavailableError
from ...settings import remote_settings
from ..proto import remote_resource_pb2, remote_resource_pb2_grpc
from .base import BaseTransport
from .utils import registry_entry


class GRPCTransport(BaseTransport):
    """Récupère une ressource distante via le RPC générique ``GetResource``.

    Le service source doit exposer le service gRPC
    ``RemoteResourceService`` défini dans ``remote/proto/remote_resource.proto``
    (voir ``remote.grpc_server.RemoteResourceServicer`` pour l'implémenter
    facilement). Un canal gRPC est ouvert et réutilisé par service
    (``target``, ``credentials``, ``max_response_bytes`` optionnels venant de
    ``REMOTE_DATA["SERVICE_REGISTRY"][service]["grpc"]``).

    Fetches a remote resource via the generic ``GetResource`` RPC.

    The source service must expose the ``RemoteResourceService`` gRPC
    service defined in ``remote/proto/remote_resource.proto`` (see
    ``remote.grpc_server.RemoteResourceServicer`` to implement it
    easily). One gRPC channel is opened and reused per service
    (``target``, optional ``credentials``, ``max_response_bytes``, coming
    from ``REMOTE_DATA["SERVICE_REGISTRY"][service]["grpc"]``).
    """

    def __init__(self) -> None:
        """Initialise le cache de canaux, vide au départ.

        Initializes the (initially empty) channel cache.
        """
        self._channels: dict[str, grpc.Channel] = {}
        self._lock = threading.Lock()

    def _channel(self, service: str, config: dict[str, Any]) -> grpc.Channel:
        """Renvoie le canal du service, en le créant et le mettant en cache si besoin.

        ``config["credentials"]`` (``grpc.ChannelCredentials``), si
        fourni, ouvre un canal chiffré (``grpc.secure_channel``) plutôt
        qu'en clair (``grpc.insecure_channel``, comportement par défaut).
        La taille max des messages reçus est bornée
        (``config["max_response_bytes"]``, sinon
        ``REMOTE_DATA["MAX_RESPONSE_BYTES"]``): protège ce consommateur
        contre un pair "de confiance" compromis ou mal configuré
        renvoyant un message démesuré.

        Returns the service's channel, creating and caching it if needed.

        ``config["credentials"]`` (``grpc.ChannelCredentials``), if
        given, opens an encrypted channel (``grpc.secure_channel``)
        instead of a plaintext one (``grpc.insecure_channel``, the
        default). The max size of received messages is bounded
        (``config["max_response_bytes"]``, otherwise
        ``REMOTE_DATA["MAX_RESPONSE_BYTES"]``): protects this consumer
        against a compromised or misconfigured "trusted" peer returning
        an oversized message.
        """
        channel = self._channels.get(service)
        if channel is not None:
            return channel
        with self._lock:
            channel = self._channels.get(service)
            if channel is None:
                target = config["target"]
                credentials = config.get("credentials")
                max_bytes = config.get(
                    "max_response_bytes", remote_settings.MAX_RESPONSE_BYTES
                )
                options = [("grpc.max_receive_message_length", max_bytes)]
                channel = (
                    grpc.secure_channel(target, credentials, options=options)
                    if credentials is not None
                    else grpc.insecure_channel(target, options=options)
                )
                self._channels[service] = channel
        return channel

    def fetch(self, *, service: str, resource: str, pk: Any) -> dict[str, Any] | None:
        """Appelle ``GetResource`` et convertit la réponse en dict, ``None`` si absent.

        Calls ``GetResource`` and converts the response to a dict, ``None`` if absent.
        """
        config = registry_entry(service, "grpc")

        if remote_settings.REQUIRE_TLS and config.get("credentials") is None:
            raise RemoteServiceMisconfiguredError(
                f"REMOTE_DATA['REQUIRE_TLS'] est actif mais aucun 'credentials' "
                f"n'est configuré pour le service '{service}' / "
                f"REMOTE_DATA['REQUIRE_TLS'] is on but no 'credentials' is "
                f"configured for service '{service}'."
            )

        channel = self._channel(service, config)
        stub = remote_resource_pb2_grpc.RemoteResourceServiceStub(channel)
        request = remote_resource_pb2.ResourceRequest(resource=resource, pk=str(pk))

        metadata = None
        auth_token = config.get("auth_token")
        if auth_token:
            # Symétrique de REMOTE_DATA["AUTH_TOKEN"] côté serveur
            # (RemoteResourceServicer / _AuthInterceptor).
            #
            # Symmetric with the server-side REMOTE_DATA["AUTH_TOKEN"]
            # (RemoteResourceServicer / _AuthInterceptor).
            metadata = (("authorization", f"Bearer {auth_token}"),)

        try:
            response = stub.GetResource(
                request, timeout=config.get("timeout", 3), metadata=metadata
            )
        except grpc.RpcError as exc:
            raise RemoteServiceUnavailableError(
                f"Appel gRPC vers '{service}' impossible / failed: {exc}"
            ) from exc

        if not response.found:
            return None
        # JSON, pas google.protobuf.Struct: Struct force tout nombre en
        # double et convertirait silencieusement un entier en flottant
        # (perte de précision au-delà de 2^53) — voir remote_resource.proto.
        try:
            return json.loads(response.data_json)
        except ValueError as exc:
            raise RemoteServiceUnavailableError(
                f"'{service}' a répondu un JSON invalide pour la ressource "
                f"'{resource}' / responded invalid JSON for resource "
                f"'{resource}': {exc}"
            ) from exc

    def close(self) -> None:
        """Ferme tous les canaux ouverts.

        Closes all open channels.
        """
        with self._lock:
            for channel in self._channels.values():
                channel.close()
            self._channels.clear()
