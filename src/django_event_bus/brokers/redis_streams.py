"""Backend Redis Streams du bus d'événements.

Redis Streams backend for the event bus.
"""

from __future__ import annotations

import logging
import os
import socket
import time
from collections.abc import Iterator
from typing import Any, cast

import redis

from ..envelope import EventEnvelope
from ..serializers import JSONEventSerializer
from .base import BaseBroker

logger = logging.getLogger("django_event_bus.redis_streams")

_FIELD = "data"
#: Erreurs réseau transitoires (LB/NAT, coupure passagère): à retenter,
#: pas à faire planter le worker.
#: Transient network errors (LB/NAT, brief outage): to retry, not to
#: crash the worker over.
_TRANSIENT_REDIS_ERRORS = (
    redis.exceptions.TimeoutError,
    redis.exceptions.ConnectionError,
)


class RedisStreamsBroker(BaseBroker):
    """Backend Redis basé sur les Streams + consumer groups.

    Pub/Sub perdrait les événements publiés pendant qu'un service est
    down. Streams + consumer groups donnent la durabilité et le
    at-least-once nécessaires à un bus inter-services: un stream par
    `event_type` (`{STREAM_PREFIX}:{event_type}`), un consumer group par
    service (`SERVICE_NAME`) pour un offset de lecture indépendant par
    service, et plusieurs workers du même service peuvent partager le
    même groupe. Un événement non acquitté après `MAX_RETRIES` tentatives
    est déplacé vers un stream `{stream}:dlq` plutôt que perdu.

    Options reconnues (`EVENT_BUS["OPTIONS"]`):
        URL: DSN redis (défaut "redis://localhost:6379/0")
        STREAM_PREFIX: préfixe des noms de stream (défaut "eventbus")
        MAX_RETRIES: tentatives avant dead-letter (défaut 3)
        BLOCK_MS: durée de blocage de XREADGROUP en ms (défaut 5000)
        RETRY_IDLE_MS: délai avant de reprendre un message resté
            pendant sans ack/fail, ex: worker mort (défaut 30000)
        CONSUMER_NAME: identifiant du worker dans le groupe (défaut
            auto: "{hostname}-{pid}")
        PUBLISH_RETRIES: tentatives supplémentaires si publish() essuie une
            coupure réseau transitoire (défaut 2)
        PUBLISH_RETRY_DELAY: délai de base (secondes) entre ces tentatives,
            multiplié par le numéro de la tentative (défaut 0.2)
        MAXLEN: longueur maximale approximative (``XADD ... MAXLEN ~``)
            conservée par stream (flux métier et dead-letter), pour éviter
            une croissance illimitée. ``None`` par défaut: pas de troncature.

    Redis backend based on Streams + consumer groups.

    Pub/Sub would lose events published while a service is down. Streams
    + consumer groups provide the durability and at-least-once semantics
    needed by an inter-service bus: one stream per `event_type`
    (`{STREAM_PREFIX}:{event_type}`), one consumer group per service
    (`SERVICE_NAME`) for an independent read offset per service, and
    several workers of the same service can share the same group. An
    event not acknowledged after `MAX_RETRIES` attempts is moved to a
    `{stream}:dlq` stream instead of being lost.

    Recognized options (`EVENT_BUS["OPTIONS"]`):
        URL: redis DSN (default "redis://localhost:6379/0")
        STREAM_PREFIX: stream name prefix (default "eventbus")
        MAX_RETRIES: attempts before dead-letter (default 3)
        BLOCK_MS: XREADGROUP blocking duration in ms (default 5000)
        RETRY_IDLE_MS: delay before reclaiming a message left pending
            without ack/fail, e.g. dead worker (default 30000)
        CONSUMER_NAME: worker identifier within the group (default
            auto: "{hostname}-{pid}")
        PUBLISH_RETRIES: extra attempts if publish() hits a transient
            network outage (default 2)
        PUBLISH_RETRY_DELAY: base delay (seconds) between those
            attempts, multiplied by the attempt number (default 0.2)
        MAXLEN: approximate maximum length (``XADD ... MAXLEN ~``) kept
            per stream (business stream and dead-letter), to avoid
            unbounded growth. Default ``None``: no trimming.
    """

    def __init__(self, *, service_name: str, options: dict) -> None:
        """Ouvre la connexion Redis et lit les options ci-dessus.

        Opens the Redis connection and reads the options above.
        """
        super().__init__(service_name=service_name, options=options)
        self.redis = redis.Redis.from_url(
            options.get("URL", "redis://localhost:6379/0")
        )
        self.prefix = options.get("STREAM_PREFIX", "eventbus")
        self.max_retries = int(options.get("MAX_RETRIES", 3))
        self.block_ms = int(options.get("BLOCK_MS", 5000))
        self.retry_idle_ms = int(options.get("RETRY_IDLE_MS", 30_000))
        default_consumer_name = f"{socket.gethostname()}-{os.getpid()}"
        self.consumer_name = options.get("CONSUMER_NAME", default_consumer_name)
        self.publish_retries = int(options.get("PUBLISH_RETRIES", 2))
        self.publish_retry_delay = float(options.get("PUBLISH_RETRY_DELAY", 0.2))
        self.maxlen = options.get("MAXLEN")
        self.serializer = JSONEventSerializer()
        self._pending: dict[str, tuple[str, bytes]] = {}

    def _stream_name(self, event_type: str) -> str:
        """Nom du stream Redis associé à ``event_type``.

        Redis stream name associated with ``event_type``.
        """
        return f"{self.prefix}:{event_type}"

    def _dlq_name(self, event_type: str) -> str:
        """Nom du stream de dead-letter associé à ``event_type``.

        Dead-letter stream name associated with ``event_type``.
        """
        return f"{self._stream_name(event_type)}:dlq"

    def publish(self, envelope: EventEnvelope) -> None:
        """Publie ``envelope``, avec quelques tentatives sur coupure réseau transitoire.

        Publishes ``envelope``, with a few retries on a transient network outage.
        """
        stream = self._stream_name(envelope.event_type)
        data: dict[str, Any] = {_FIELD: self.serializer.dumps(envelope)}
        attempts = self.publish_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                # Le stub redis-py type ce paramètre en dict[UnionKey,
                # UnionValue] invariant: aucun dict concret typé (même
                # dict[str, Any]) ne le satisfait statiquement.
                #
                # The redis-py stub types this parameter as an invariant
                # dict[UnionKey, UnionValue]: no concretely-typed dict
                # (even dict[str, Any]) satisfies it statically.
                self.redis.xadd(
                    stream,
                    data,  # type: ignore[arg-type]
                    maxlen=self.maxlen,
                    approximate=True,
                )
                return
            except _TRANSIENT_REDIS_ERRORS:
                if attempt == attempts:
                    raise
                logger.warning(
                    "Publication de %s interrompue (tentative %s/%s), nouvel essai",
                    envelope.event_type,
                    attempt,
                    attempts,
                )
                time.sleep(self.publish_retry_delay * attempt)

    def _ensure_group(self, stream: str, *, start_id: str = "0") -> None:
        """Crée le consumer group du stream s'il n'existe pas déjà.

        ``start_id="0"`` par défaut: une création initiale (``listen()``)
        doit lire tout l'historique du stream. ``_recover_missing_group``
        recrée volontairement avec ``start_id="$"`` — voir sa docstring.

        Creates the stream's consumer group if it does not already exist.

        ``start_id="0"`` by default: an initial creation (``listen()``)
        must read the stream's full history. ``_recover_missing_group``
        deliberately recreates with ``start_id="$"`` — see its docstring.
        """
        try:
            self.redis.xgroup_create(
                stream, self.service_name, id=start_id, mkstream=True
            )
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def listen(self, event_types: set[str]) -> Iterator[EventEnvelope]:
        """Crée les consumer groups puis renvoie l'itérateur de consommation.

        Les consumer groups sont créés ici, avant de retourner: une
        fonction génératrice n'exécute rien avant le premier next(), ce
        qui retarderait leur création jusqu'à la première itération.

        Creates the consumer groups then returns the consuming iterator.

        The consumer groups are created here, before returning: a
        generator function runs nothing before the first next(), which
        would delay their creation until the first iteration.
        """
        streams = {
            event_type: self._stream_name(event_type) for event_type in event_types
        }
        for stream in streams.values():
            self._ensure_group(stream)
        return self._consume(streams)

    def _consume(self, streams: dict[str, str]) -> Iterator[EventEnvelope]:
        """Reprend les messages en attente puis lit les nouveaux, en boucle.

        Reclaims pending messages then reads new ones, in a loop.
        """
        while True:
            # Reprend d'abord les messages restés pendants trop longtemps
            # (worker précédent mort, ou fail() qui les a laissés en attente).
            for stream in streams.values():
                try:
                    _cursor, claimed, _deleted = self.redis.xautoclaim(
                        stream,
                        self.service_name,
                        self.consumer_name,
                        min_idle_time=self.retry_idle_ms,
                        start_id="0-0",
                        count=10,
                    )
                except redis.ResponseError as exc:
                    self._recover_missing_group(stream, exc)
                    continue
                except _TRANSIENT_REDIS_ERRORS as exc:
                    self._log_transient_redis_error(
                        "la reprise des messages en attente", exc
                    )
                    continue
                for msg_id, fields in claimed:
                    envelope = self._to_envelope(stream, msg_id, fields)
                    if envelope is not None:
                        yield envelope

            try:
                # redis-py type les réponses XREADGROUP de façon très
                # permissive (RESP est dynamiquement typé): la forme
                # réelle ici est bien list[(stream, [(id, fields), ...])].
                #
                # redis-py types XREADGROUP responses very loosely (RESP
                # is dynamically typed): the actual shape here is indeed
                # list[(stream, [(id, fields), ...])].
                response = cast(
                    "list[tuple[bytes, list[tuple[bytes, dict[bytes, bytes]]]]] | None",
                    self.redis.xreadgroup(
                        self.service_name,
                        self.consumer_name,
                        dict.fromkeys(streams.values(), ">"),
                        count=10,
                        block=self.block_ms,
                    ),
                )
            except redis.ResponseError as exc:
                for stream in streams.values():
                    self._recover_missing_group(stream, exc)
                continue
            except _TRANSIENT_REDIS_ERRORS as exc:
                # Un délai d'inactivité réseau (LB/NAT) ou une coupure
                # transitoire peut interrompre la lecture bloquante avant
                # que Redis n'ait répondu: ce n'est pas une perte de
                # message (rien n'a été livré), juste un cycle à refaire
                # — redis-py reconnecte tout seul à la prochaine commande.
                self._log_transient_redis_error("l'écoute", exc)
                continue
            for raw_stream, messages in response or []:
                stream_name = raw_stream.decode()
                for msg_id, fields in messages:
                    envelope = self._to_envelope(stream_name, msg_id, fields)
                    if envelope is not None:
                        yield envelope

    def _log_transient_redis_error(self, phase: str, exc: Exception) -> None:
        """Journalise une coupure réseau transitoire pendant ``phase``.

        Logs a transient network outage during ``phase``.
        """
        logger.warning(
            "Connexion Redis interrompue pendant %s (%s), nouvelle tentative",
            phase,
            exc,
        )

    def _recover_missing_group(self, stream: str, exc: redis.ResponseError) -> None:
        """Recrée le consumer group manquant (NOGROUP), relève l'erreur sinon.

        Le consumer group a pu disparaître (flush, suppression manuelle)
        alors que le stream, lui, existe toujours: le recréer avec
        ``start_id="0"`` (comportement d'une création initiale) rejouerait
        alors tout l'historique du stream, y compris des messages acquittés
        depuis longtemps — ``XACK`` retire une entrée du PEL du groupe, pas
        du stream. On recrée donc à partir de ``"$"`` (uniquement les
        messages à venir) pour éviter cette tempête de retraitement; le
        prix est qu'un message publié entre la disparition du groupe et sa
        recréation peut être manqué, un compromis déjà implicite dès lors
        que l'état du groupe a été perdu.

        Recreates the missing (NOGROUP) consumer group, re-raises otherwise.

        The consumer group may have disappeared (flush, manual removal)
        while the stream itself still exists: recreating it with
        ``start_id="0"`` (initial-creation behavior) would then replay the
        stream's entire history, including messages acknowledged long ago
        — ``XACK`` removes an entry from the group's PEL, not from the
        stream. It is therefore recreated from ``"$"`` (only upcoming
        messages) to avoid this reprocessing storm; the cost is that a
        message published between the group's disappearance and its
        recreation can be missed, a trade-off already implicit once the
        group's state was lost.
        """
        if "NOGROUP" not in str(exc):
            raise exc
        logger.error("Consumer group manquant sur %s, recréation (%s)", stream, exc)
        self._ensure_group(stream, start_id="$")

    def _to_envelope(
        self, stream: str, msg_id: bytes, fields: dict[bytes, bytes]
    ) -> EventEnvelope | None:
        """Désérialise un message, ``None`` (et acquittement) s'il est illisible.

        Message illisible (schéma incompatible, corruption, ...): il est
        retiré du flux pour ne pas bloquer le worker en boucle sur un
        message qu'il ne pourra jamais traiter avec succès.

        Deserializes a message, ``None`` (and acknowledged) if unreadable.

        Unreadable message (incompatible schema, corruption, ...): it is
        removed from the stream so as not to block the worker in a loop
        on a message it could never process successfully.
        """
        try:
            # decode_responses n'est pas activé sur le client: les champs
            # reviennent en bytes, clé b"data" incluse (KeyError si le
            # message n'a pas ce champ, traité ci-dessous comme illisible).
            #
            # decode_responses is not enabled on the client: fields come
            # back as bytes, including the b"data" key (KeyError if the
            # message lacks that field, handled below as unreadable).
            envelope = self.serializer.loads(fields[b"data"])
        except Exception:
            logger.exception(
                "Message illisible sur %s (id=%s) — acquitté sans traitement",
                stream,
                msg_id,
            )
            self.redis.xack(stream, self.service_name, msg_id)
            return None
        self._pending[envelope.event_id] = (stream, msg_id)
        return envelope

    def ack(self, envelope: EventEnvelope) -> None:
        """Acquitte ``envelope`` auprès de Redis (XACK).

        Acknowledges ``envelope`` with Redis (XACK).
        """
        stream, msg_id = self._pending.pop(envelope.event_id, (None, None))
        if stream is None or msg_id is None:
            return
        self.redis.xack(stream, self.service_name, msg_id)

    def fail(self, envelope: EventEnvelope) -> bool:
        """Retente ou déplace ``envelope`` en dead-letter selon le nombre de tentatives.

        Retries or moves ``envelope`` to dead-letter depending on the attempt count.
        """
        stream, msg_id = self._pending.pop(envelope.event_id, (None, None))
        if stream is None or msg_id is None:
            return True

        pending_info = self.redis.xpending_range(
            stream, self.service_name, min=msg_id, max=msg_id, count=1
        )
        delivery_count = int(pending_info[0]["times_delivered"]) if pending_info else 1

        if delivery_count < self.max_retries:
            logger.warning(
                "Échec de traitement de %s (%s), tentative %s/%s — sera retenté",
                envelope.event_type,
                envelope.event_id,
                delivery_count,
                self.max_retries,
            )
            return False

        logger.error(
            "Échec définitif de %s (%s) après %s tentatives — déplacé en dead-letter",
            envelope.event_type,
            envelope.event_id,
            delivery_count,
        )
        # MULTI/EXEC: si le worker meurt entre les deux écritures, aucune
        # des deux n'a lieu plutôt que de dupliquer l'entrée en dead-letter
        # à la prochaine reprise du message.
        with self.redis.pipeline(transaction=True) as pipe:
            dlq_data: dict[str, Any] = {_FIELD: self.serializer.dumps(envelope)}
            # Voir le commentaire équivalent dans publish() ci-dessus.
            # See the equivalent comment in publish() above.
            pipe.xadd(
                self._dlq_name(envelope.event_type),
                dlq_data,  # type: ignore[arg-type]
                maxlen=self.maxlen,
                approximate=True,
            )
            pipe.xack(stream, self.service_name, msg_id)
            pipe.execute()
        return True

    def close(self) -> None:
        """Ferme la connexion Redis.

        Closes the Redis connection.
        """
        self.redis.close()
