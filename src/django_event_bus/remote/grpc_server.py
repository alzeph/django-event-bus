"""Serveur gRPC réutilisable exposant le RPC générique ``GetResource``.

Reusable gRPC server exposing the generic ``GetResource`` RPC.
"""

from __future__ import annotations

import hmac
import json
import logging
import signal
import threading
from collections.abc import Callable, Sequence
from concurrent import futures
from typing import Any

import grpc
from django.core.serializers.json import DjangoJSONEncoder

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
        # JSON (via DjangoJSONEncoder, comme le bus d'événements), pas
        # google.protobuf.Struct: voir remote_resource.proto pour le pourquoi.
        data_json = json.dumps(data, cls=DjangoJSONEncoder)
        return remote_resource_pb2.ResourceResponse(found=True, data_json=data_json)


def _unauthenticated_handler() -> grpc.RpcMethodHandler:
    """Handler générique qui rejette l'appel en ``UNAUTHENTICATED``.

    Generic handler that rejects the call as ``UNAUTHENTICATED``.
    """

    def terminate(
        _request: Any, context: grpc.ServicerContext
    ) -> remote_resource_pb2.ResourceResponse:
        context.abort(grpc.StatusCode.UNAUTHENTICATED, "invalid or missing token")
        # pragma: no cover — context.abort() always raises, never returns.
        raise AssertionError("unreachable")

    return grpc.unary_unary_rpc_method_handler(terminate)


class _TokenAuthInterceptor(grpc.ServerInterceptor):
    """Rejette tout appel sans métadonnée ``authorization: Bearer <token>`` valide.

    Symétrique du contrôle fait côté HTTP par
    ``remote.views._is_authorized``: même secret partagé
    (``REMOTE_DATA["AUTH_TOKEN"]``), même comparaison à temps constant.

    Rejects any call without a valid ``authorization: Bearer <token>``
    metadata entry.

    Symmetric with the HTTP-side check in ``remote.views._is_authorized``:
    same shared secret (``REMOTE_DATA["AUTH_TOKEN"]``), same constant-time
    comparison.
    """

    def __init__(self, token: str) -> None:
        """Mémorise le token attendu et prépare le handler de rejet.

        Stores the expected token and prepares the rejection handler.
        """
        self._token = token
        self._unauthenticated = _unauthenticated_handler()

    def intercept_service(
        self,
        continuation: Callable[[grpc.HandlerCallDetails], grpc.RpcMethodHandler],
        handler_call_details: grpc.HandlerCallDetails,
    ) -> grpc.RpcMethodHandler:
        """Laisse passer l'appel si le token présenté correspond, le rejette sinon.

        Passes the call through if the presented token matches, rejects it otherwise.
        """
        metadata = dict(handler_call_details.invocation_metadata or ())
        presented = metadata.get("authorization", "")
        if not hmac.compare_digest(presented, f"Bearer {self._token}"):
            return self._unauthenticated
        return continuation(handler_call_details)


def serve(
    resolve: ResourceResolver,
    *,
    port: int = 50051,
    max_workers: int = 10,
    auth_token: str | None = None,
    credentials: grpc.ServerCredentials | None = None,
    interceptors: Sequence[grpc.ServerInterceptor] = (),
) -> None:
    """Démarre un serveur gRPC bloquant exposant ``GetResource`` via ``resolve``.

    S'arrête proprement sur ``SIGINT``/``SIGTERM`` (même logique que la
    commande ``eventbus_worker`` du bus d'événements).

    ``auth_token``: si fourni, tout appel doit présenter la métadonnée
    ``authorization: Bearer <auth_token>`` (voir ``_TokenAuthInterceptor``).
    ``credentials``: si fourni (``grpc.ssl_server_credentials(...)``, ...),
    sert en TLS (``add_secure_port``) plutôt qu'en clair
    (``add_insecure_port``, comportement par défaut si omis).
    ``interceptors``: interceptors gRPC additionnels (ex: rate limiting
    maison), appliqués après ``auth_token`` s'il est aussi fourni.

    Starts a blocking gRPC server exposing ``GetResource`` via ``resolve``.

    Stops cleanly on ``SIGINT``/``SIGTERM`` (same logic as the event
    bus's ``eventbus_worker`` command).

    ``auth_token``: if given, every call must present the
    ``authorization: Bearer <auth_token>`` metadata entry (see
    ``_TokenAuthInterceptor``).
    ``credentials``: if given (``grpc.ssl_server_credentials(...)``, ...),
    serves over TLS (``add_secure_port``) instead of in the clear
    (``add_insecure_port``, the default if omitted).
    ``interceptors``: additional gRPC interceptors (e.g. a custom rate
    limiter), applied after ``auth_token``'s if that one is also given.
    """
    all_interceptors: list[grpc.ServerInterceptor] = list(interceptors)
    if auth_token:
        all_interceptors.insert(0, _TokenAuthInterceptor(auth_token))

    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=max_workers),
        interceptors=all_interceptors,
    )
    remote_resource_pb2_grpc.add_RemoteResourceServiceServicer_to_server(
        RemoteResourceServicer(resolve), server
    )
    if credentials is not None:
        server.add_secure_port(f"[::]:{port}", credentials)
    else:
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
