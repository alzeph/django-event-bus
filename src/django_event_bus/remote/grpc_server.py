"""Serveur gRPC réutilisable exposant le RPC générique ``GetResource``.

Reusable gRPC server exposing the generic ``GetResource`` RPC.
"""

from __future__ import annotations

import json
import logging
import signal
import threading
from collections.abc import Callable, Sequence
from concurrent import futures
from typing import Any

import grpc
from django.core.serializers.json import DjangoJSONEncoder

from . import audit
from .auth import AllowAllAuthBackend, BaseAuthBackend, StaticTokenAuthBackend
from .proto import remote_resource_pb2, remote_resource_pb2_grpc
from .ratelimit import RateLimitConfig, is_allowed

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

    def __init__(
        self, resolve: ResourceResolver, *, auth_backend: BaseAuthBackend | None = None
    ) -> None:
        """Reçoit la fonction de résolution et le backend d'auth (pour l'audit).

        ``auth_backend`` n'est pas utilisé ici pour décider de
        l'accès — c'est déjà tranché en amont par ``_AuthInterceptor``,
        si configuré. Il ne sert qu'à retrouver l'identité de l'appelant
        (``AuthResult.caller``) pour le journal d'audit.

        Receives the resolver function and the auth backend (for auditing).

        ``auth_backend`` is not used here to decide access — that is
        already settled upstream by ``_AuthInterceptor``, if configured.
        It is only used to recover the caller's identity
        (``AuthResult.caller``) for the audit log.
        """
        self._resolve = resolve
        self._auth_backend = auth_backend or AllowAllAuthBackend()

    def GetResource(  # noqa: N802 - nom imposé par le service gRPC généré / name imposed by generated gRPC service
        self,
        request: remote_resource_pb2.ResourceRequest,
        context: grpc.ServicerContext,
    ) -> remote_resource_pb2.ResourceResponse:
        """Résout la ressource demandée et la sérialise en ``ResourceResponse``.

        Resolves the requested resource and serializes it into a ``ResourceResponse``.
        """
        metadata = dict(context.invocation_metadata() or ())
        caller = self._auth_backend.authenticate(metadata.get("authorization")).caller
        audit.log_access(
            transport="grpc",
            granted=True,
            peer=context.peer(),
            resource=request.resource,
            pk=request.pk,
            caller=caller,
        )

        data = self._resolve(request.resource, request.pk)
        if data is None:
            return remote_resource_pb2.ResourceResponse(found=False)
        # JSON (via DjangoJSONEncoder, comme le bus d'événements), pas
        # google.protobuf.Struct: voir remote_resource.proto pour le pourquoi.
        data_json = json.dumps(data, cls=DjangoJSONEncoder)
        return remote_resource_pb2.ResourceResponse(found=True, data_json=data_json)


def _wrap_unary_unary(
    handler: grpc.RpcMethodHandler | None,
    wrapper: Callable[
        [Callable[[Any, grpc.ServicerContext], Any], Any, grpc.ServicerContext], Any
    ],
) -> grpc.RpcMethodHandler | None:
    """Enveloppe le comportement unary-unary d'un handler, s'il en a un.

    ``GetResource`` est le seul RPC du service (unary-unary): les autres
    formes (streaming, etc.) traversent l'intercepteur inchangées.

    Wraps a handler's unary-unary behavior, if it has one.

    ``GetResource`` is the service's only RPC (unary-unary): other
    shapes (streaming, etc.) pass through the interceptor unchanged.
    """
    if handler is None or handler.unary_unary is None:
        return handler
    original_behavior = handler.unary_unary

    def behavior(request: Any, context: grpc.ServicerContext) -> Any:
        return wrapper(original_behavior, request, context)

    return grpc.unary_unary_rpc_method_handler(
        behavior,
        request_deserializer=handler.request_deserializer,
        response_serializer=handler.response_serializer,
    )


class _RateLimitInterceptor(grpc.ServerInterceptor):
    """Rejette en ``RESOURCE_EXHAUSTED`` un pair dépassant sa limite d'appels.

    Rejects, as ``RESOURCE_EXHAUSTED``, a peer exceeding its call limit.
    """

    def __init__(self, config: RateLimitConfig) -> None:
        """Mémorise la configuration de la limite.

        Stores the limit's configuration.
        """
        self._config = config

    def intercept_service(
        self,
        continuation: Callable[[grpc.HandlerCallDetails], grpc.RpcMethodHandler],
        handler_call_details: grpc.HandlerCallDetails,
    ) -> grpc.RpcMethodHandler | None:
        """Enveloppe le handler pour vérifier la limite avant de l'exécuter.

        Wraps the handler to check the limit before running it.
        """
        handler = continuation(handler_call_details)

        def wrapper(
            original_behavior: Callable[[Any, grpc.ServicerContext], Any],
            request: Any,
            context: grpc.ServicerContext,
        ) -> Any:
            peer = context.peer() or "-"
            if not is_allowed(self._config, peer):
                audit.log_access(
                    transport="grpc", granted=False, peer=peer, reason="rate limited"
                )
                context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, "rate limit exceeded")
            return original_behavior(request, context)

        return _wrap_unary_unary(handler, wrapper)


class _AuthInterceptor(grpc.ServerInterceptor):
    """Rejette en ``UNAUTHENTICATED`` un appel que ``backend`` n'autorise pas.

    Rejects, as ``UNAUTHENTICATED``, a call that ``backend`` does not authorize.
    """

    def __init__(self, backend: BaseAuthBackend) -> None:
        """Mémorise le backend d'authentification à consulter.

        Stores the authentication backend to consult.
        """
        self._backend = backend

    def intercept_service(
        self,
        continuation: Callable[[grpc.HandlerCallDetails], grpc.RpcMethodHandler],
        handler_call_details: grpc.HandlerCallDetails,
    ) -> grpc.RpcMethodHandler | None:
        """Enveloppe le handler pour vérifier l'authentification avant de l'exécuter.

        Wraps the handler to check authentication before running it.
        """
        handler = continuation(handler_call_details)
        metadata = dict(handler_call_details.invocation_metadata or ())
        authorization = metadata.get("authorization")

        def wrapper(
            original_behavior: Callable[[Any, grpc.ServicerContext], Any],
            request: Any,
            context: grpc.ServicerContext,
        ) -> Any:
            result = self._backend.authenticate(authorization)
            if not result.granted:
                audit.log_access(
                    transport="grpc",
                    granted=False,
                    peer=context.peer(),
                    reason=result.reason,
                )
                context.abort(
                    grpc.StatusCode.UNAUTHENTICATED, result.reason or "unauthorized"
                )
            return original_behavior(request, context)

        return _wrap_unary_unary(handler, wrapper)


def serve(
    resolve: ResourceResolver,
    *,
    port: int = 50051,
    max_workers: int = 10,
    auth_token: str | None = None,
    auth_backend: BaseAuthBackend | None = None,
    credentials: grpc.ServerCredentials | None = None,
    interceptors: Sequence[grpc.ServerInterceptor] = (),
    rate_limit: RateLimitConfig | None = None,
    max_message_bytes: int | None = None,
) -> None:
    """Démarre un serveur gRPC bloquant exposant ``GetResource`` via ``resolve``.

    S'arrête proprement sur ``SIGINT``/``SIGTERM`` (même logique que la
    commande ``eventbus_worker`` du bus d'événements).

    ``auth_token``: raccourci équivalent à
    ``auth_backend=StaticTokenAuthBackend(auth_token)``, conservé pour
    compatibilité. ``auth_backend``, s'il est fourni, est prioritaire.
    ``credentials``: si fourni (``grpc.ssl_server_credentials(...)``, ...),
    sert en TLS (``add_secure_port``) plutôt qu'en clair
    (``add_insecure_port``, comportement par défaut si omis).
    ``rate_limit``: limite d'appels par pair (adresse gRPC), vérifiée
    avant l'authentification. ``interceptors``: interceptors gRPC
    additionnels, appliqués après ``rate_limit`` et ``auth_token``/
    ``auth_backend``. ``max_message_bytes``: taille max (octets) des
    messages reçus/envoyés (``grpc.max_receive_message_length``/
    ``grpc.max_send_message_length``); ``None`` conserve la limite par
    défaut de grpc.

    Starts a blocking gRPC server exposing ``GetResource`` via ``resolve``.

    Stops cleanly on ``SIGINT``/``SIGTERM`` (same logic as the event
    bus's ``eventbus_worker`` command).

    ``auth_token``: shorthand equivalent to
    ``auth_backend=StaticTokenAuthBackend(auth_token)``, kept for
    backward compatibility. ``auth_backend``, if given, takes
    precedence. ``credentials``: if given
    (``grpc.ssl_server_credentials(...)``, ...), serves over TLS
    (``add_secure_port``) instead of in the clear
    (``add_insecure_port``, the default if omitted). ``rate_limit``: a
    per-peer (gRPC address) call limit, checked before authentication.
    ``interceptors``: additional gRPC interceptors, applied after
    ``rate_limit`` and ``auth_token``/``auth_backend``.
    ``max_message_bytes``: max size (bytes) of received/sent messages
    (``grpc.max_receive_message_length``/``grpc.max_send_message_length``);
    ``None`` keeps grpc's own default limit.
    """
    effective_backend = auth_backend
    if effective_backend is None and auth_token:
        effective_backend = StaticTokenAuthBackend(auth_token)

    all_interceptors: list[grpc.ServerInterceptor] = []
    if rate_limit is not None:
        all_interceptors.append(_RateLimitInterceptor(rate_limit))
    if effective_backend is not None:
        all_interceptors.append(_AuthInterceptor(effective_backend))
    all_interceptors.extend(interceptors)

    server_options = None
    if max_message_bytes is not None:
        server_options = [
            ("grpc.max_receive_message_length", max_message_bytes),
            ("grpc.max_send_message_length", max_message_bytes),
        ]

    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=max_workers),
        interceptors=all_interceptors,
        options=server_options,
    )
    remote_resource_pb2_grpc.add_RemoteResourceServiceServicer_to_server(
        RemoteResourceServicer(resolve, auth_backend=effective_backend), server
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
