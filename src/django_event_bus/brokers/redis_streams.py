from __future__ import annotations

import logging
import os
import socket
import time
from collections.abc import Iterator

import redis

from ..envelope import EventEnvelope
from ..serializers import JSONEventSerializer
from .base import BaseBroker

logger = logging.getLogger("django_event_bus.redis_streams")

_FIELD = "data"


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
    """

    def __init__(self, *, service_name: str, options: dict):
        super().__init__(service_name=service_name, options=options)
        self.redis = redis.Redis.from_url(options.get("URL", "redis://localhost:6379/0"))
        self.prefix = options.get("STREAM_PREFIX", "eventbus")
        self.max_retries = int(options.get("MAX_RETRIES", 3))
        self.block_ms = int(options.get("BLOCK_MS", 5000))
        self.retry_idle_ms = int(options.get("RETRY_IDLE_MS", 30_000))
        self.consumer_name = options.get(
            "CONSUMER_NAME", f"{socket.gethostname()}-{os.getpid()}"
        )
        self.publish_retries = int(options.get("PUBLISH_RETRIES", 2))
        self.publish_retry_delay = float(options.get("PUBLISH_RETRY_DELAY", 0.2))
        self.serializer = JSONEventSerializer()
        self._pending: dict[str, tuple[str, bytes]] = {}

    def _stream_name(self, event_type: str) -> str:
        return f"{self.prefix}:{event_type}"

    def _dlq_name(self, event_type: str) -> str:
        return f"{self._stream_name(event_type)}:dlq"

    def publish(self, envelope: EventEnvelope) -> None:
        stream = self._stream_name(envelope.event_type)
        data = {_FIELD: self.serializer.dumps(envelope)}
        attempts = self.publish_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                self.redis.xadd(stream, data)
                return
            except (redis.exceptions.TimeoutError, redis.exceptions.ConnectionError):
                if attempt == attempts:
                    raise
                logger.warning(
                    "Publication de %s interrompue (tentative %s/%s), nouvel essai",
                    envelope.event_type,
                    attempt,
                    attempts,
                )
                time.sleep(self.publish_retry_delay * attempt)

    def _ensure_group(self, stream: str) -> None:
        try:
            self.redis.xgroup_create(stream, self.service_name, id="0", mkstream=True)
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def listen(self, event_types: set[str]) -> Iterator[EventEnvelope]:
        # Les consumer groups sont créés ici, avant de retourner: une
        # fonction génératrice n'exécute rien avant le premier next(), ce
        # qui retarderait leur création jusqu'à la première itération.
        streams = {event_type: self._stream_name(event_type) for event_type in event_types}
        for stream in streams.values():
            self._ensure_group(stream)
        return self._consume(streams)

    def _consume(self, streams: dict[str, str]) -> Iterator[EventEnvelope]:
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
                except (redis.exceptions.TimeoutError, redis.exceptions.ConnectionError) as exc:
                    self._log_transient_redis_error("la reprise des messages en attente", exc)
                    continue
                for msg_id, fields in claimed:
                    envelope = self._to_envelope(stream, msg_id, fields)
                    if envelope is not None:
                        yield envelope

            try:
                response = self.redis.xreadgroup(
                    self.service_name,
                    self.consumer_name,
                    {stream: ">" for stream in streams.values()},
                    count=10,
                    block=self.block_ms,
                )
            except redis.ResponseError as exc:
                for stream in streams.values():
                    self._recover_missing_group(stream, exc)
                continue
            except (redis.exceptions.TimeoutError, redis.exceptions.ConnectionError) as exc:
                # Un délai d'inactivité réseau (LB/NAT) ou une coupure
                # transitoire peut interrompre la lecture bloquante avant
                # que Redis n'ait répondu: ce n'est pas une perte de
                # message (rien n'a été livré), juste un cycle à refaire
                # — redis-py reconnecte tout seul à la prochaine commande.
                self._log_transient_redis_error("l'écoute", exc)
                continue
            for stream, messages in response or []:
                stream = stream.decode() if isinstance(stream, bytes) else stream
                for msg_id, fields in messages:
                    envelope = self._to_envelope(stream, msg_id, fields)
                    if envelope is not None:
                        yield envelope

    def _log_transient_redis_error(self, phase: str, exc: Exception) -> None:
        logger.warning("Connexion Redis interrompue pendant %s (%s), nouvelle tentative", phase, exc)

    def _recover_missing_group(self, stream: str, exc: redis.ResponseError) -> None:
        # Le consumer group a pu disparaître (flush, suppression manuelle):
        # on le recrée plutôt que de planter le worker en boucle.
        if "NOGROUP" not in str(exc):
            raise exc
        logger.error("Consumer group manquant sur %s, recréation (%s)", stream, exc)
        self._ensure_group(stream)

    def _to_envelope(self, stream: str, msg_id: bytes, fields: dict) -> EventEnvelope | None:
        raw = fields.get(b"data", fields.get(_FIELD))
        try:
            envelope = self.serializer.loads(raw)
        except Exception:
            # Message illisible (schéma incompatible, corruption, ...): on
            # le retire du flux pour ne pas bloquer le worker en boucle sur
            # un message qu'il ne pourra jamais traiter avec succès.
            logger.exception(
                "Message illisible sur %s (id=%s) — acquitté sans traitement", stream, msg_id
            )
            self.redis.xack(stream, self.service_name, msg_id)
            return None
        self._pending[envelope.event_id] = (stream, msg_id)
        return envelope

    def ack(self, envelope: EventEnvelope) -> None:
        stream, msg_id = self._pending.pop(envelope.event_id, (None, None))
        if stream is None:
            return
        self.redis.xack(stream, self.service_name, msg_id)

    def fail(self, envelope: EventEnvelope) -> bool:
        stream, msg_id = self._pending.pop(envelope.event_id, (None, None))
        if stream is None:
            return True

        pending_info = self.redis.xpending_range(
            stream, self.service_name, min=msg_id, max=msg_id, count=1
        )
        delivery_count = pending_info[0]["times_delivered"] if pending_info else 1

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
            pipe.xadd(self._dlq_name(envelope.event_type), {_FIELD: self.serializer.dumps(envelope)})
            pipe.xack(stream, self.service_name, msg_id)
            pipe.execute()
        return True

    def close(self) -> None:
        self.redis.close()
