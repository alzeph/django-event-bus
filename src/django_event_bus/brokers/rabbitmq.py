"""Backend RabbitMQ du bus d'événements.

RabbitMQ backend for the event bus.
"""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Iterator
from typing import Any

import pika
import pika.exceptions

from ..envelope import EventEnvelope
from ..serializers import JSONEventSerializer
from .base import BaseBroker

logger = logging.getLogger("django_event_bus.rabbitmq")

#: Erreurs de connexion transitoires (LB/NAT, coupure passagère, broker
#: qui redémarre): à retenter, pas à faire planter le worker.
#: Transient connection errors (LB/NAT, brief outage, broker
#: restarting): to retry, not to crash the worker over.
_TRANSIENT_AMQP_ERRORS = (
    pika.exceptions.AMQPConnectionError,
    pika.exceptions.ConnectionClosed,
    pika.exceptions.ChannelClosed,
    pika.exceptions.StreamLostError,
)


class RabbitMQBroker(BaseBroker):
    """Backend RabbitMQ basé sur un exchange direct + file de retry par TTL.

    Une file par (`service_name`, `event_type`)
    (`{EXCHANGE_PREFIX}.{service_name}.{event_type}`), liée à un exchange
    direct partagé (`{EXCHANGE_PREFIX}`) avec `event_type` comme routing
    key — l'équivalent du consumer group Redis: chaque service consomme
    sa propre file, indépendamment des autres.

    RabbitMQ ne trackant pas nativement un nombre de tentatives par
    message, `fail()` s'appuie sur le header `x-death` que RabbitMQ
    ajoute lui-même à chaque passage par une dead-letter-exchange: un
    message en échec est `nack`é (`requeue=False`) vers une file de
    retry dont le TTL (`RETRY_DELAY_MS`) le renvoie automatiquement vers
    la file principale une fois expiré. `x-death` porte ainsi le nombre
    de tentatives de façon durable côté broker, comme `XPENDING` pour
    Redis. Au-delà de `MAX_RETRIES`, le message est publié sur
    `{queue}.dlq` puis acquitté sur la file principale.

    Contrairement aux backends Redis Streams et Kafka, les files
    RabbitMQ ne conservent pas d'historique indépendant de leur
    existence: un message publié alors qu'aucun service n'a encore
    jamais appelé `listen()` pour ce `event_type` (donc jamais déclaré
    sa file) est perdu, l'exchange n'ayant personne à qui le router.
    Une fois la file déclarée (au premier `listen()`, ou par un
    déploiement qui démarre au moins une fois `eventbus_worker`), elle
    est durable et retient les messages y compris pendant que ce
    service est arrêté.

    Options reconnues (`EVENT_BUS["OPTIONS"]`):
        URL: DSN AMQP (défaut "amqp://guest:guest@localhost:5672/%2F")
        EXCHANGE_PREFIX: préfixe des exchanges/files (défaut "eventbus")
        MAX_RETRIES: tentatives avant dead-letter (défaut 3)
        RETRY_DELAY_MS: délai (TTL) avant qu'un message en échec ne
            revienne dans la file principale (défaut 5000)
        PREFETCH_COUNT: messages non acquittés simultanés par consumer
            (défaut 10)
        POLL_INTERVAL: délai d'inactivité (secondes) entre deux files
            lors du parcours round-robin de listen() (défaut 0.5)
        PUBLISH_RETRIES: tentatives supplémentaires si publish() essuie
            une coupure réseau transitoire (défaut 2)
        PUBLISH_RETRY_DELAY: délai de base (secondes) entre ces
            tentatives, multiplié par le numéro de la tentative (défaut
            0.2)

    RabbitMQ backend based on a direct exchange + a TTL retry queue.

    One queue per (`service_name`, `event_type`)
    (`{EXCHANGE_PREFIX}.{service_name}.{event_type}`), bound to a shared
    direct exchange (`{EXCHANGE_PREFIX}`) with `event_type` as the
    routing key — the equivalent of Redis's consumer group: each
    service consumes its own queue, independently of the others.

    Since RabbitMQ doesn't natively track a per-message attempt count,
    `fail()` relies on the `x-death` header that RabbitMQ itself adds on
    every pass through a dead-letter-exchange: a failed message is
    `nack`ed (`requeue=False`) to a retry queue whose TTL
    (`RETRY_DELAY_MS`) sends it back to the main queue once expired.
    `x-death` thus carries the attempt count durably on the broker
    side, like `XPENDING` for Redis. Past `MAX_RETRIES`, the message is
    published to `{queue}.dlq` then acknowledged on the main queue.

    Unlike the Redis Streams and Kafka backends, RabbitMQ queues retain
    no history independent of their existence: a message published
    while no service has ever called `listen()` for that `event_type`
    yet (and so never declared its queue) is lost, the exchange having
    no one to route it to. Once the queue is declared (on the first
    `listen()`, or by a deployment that starts `eventbus_worker` at
    least once), it is durable and retains messages even while that
    service is stopped.

    Recognized options (`EVENT_BUS["OPTIONS"]`):
        URL: AMQP DSN (default "amqp://guest:guest@localhost:5672/%2F")
        EXCHANGE_PREFIX: exchange/queue name prefix (default "eventbus")
        MAX_RETRIES: attempts before dead-letter (default 3)
        RETRY_DELAY_MS: delay (TTL) before a failed message returns to
            the main queue (default 5000)
        PREFETCH_COUNT: simultaneous unacknowledged messages per
            consumer (default 10)
        POLL_INTERVAL: inactivity delay (seconds) between queues while
            round-robining in listen() (default 0.5)
        PUBLISH_RETRIES: extra attempts if publish() hits a transient
            network outage (default 2)
        PUBLISH_RETRY_DELAY: base delay (seconds) between those
            attempts, multiplied by the attempt number (default 0.2)
    """

    def __init__(self, *, service_name: str, options: dict) -> None:
        """Ouvre la connexion AMQP, déclare les exchanges partagés.

        Opens the AMQP connection, declares the shared exchanges, and
        reads the options above.
        """
        super().__init__(service_name=service_name, options=options)
        self.url = options.get("URL", "amqp://guest:guest@localhost:5672/%2F")
        self.prefix = options.get("EXCHANGE_PREFIX", "eventbus")
        self.max_retries = int(options.get("MAX_RETRIES", 3))
        self.retry_delay_ms = int(options.get("RETRY_DELAY_MS", 5000))
        self.prefetch_count = int(options.get("PREFETCH_COUNT", 10))
        self.poll_interval = float(options.get("POLL_INTERVAL", 0.5))
        self.publish_retries = int(options.get("PUBLISH_RETRIES", 2))
        self.publish_retry_delay = float(options.get("PUBLISH_RETRY_DELAY", 0.2))
        self.serializer = JSONEventSerializer()

        self.exchange = self.prefix
        self.retry_exchange = f"{self.prefix}.retry"
        self.dlq_exchange = f"{self.prefix}.dlq"

        self._connection = self._connect()
        self._channel = self._connection.channel()
        self._declare_exchanges()

        #: event_type -> (canal dédié, générateur de consommation).
        #: Un canal par file: BlockingChannel.consume() ne supporte
        #: qu'un seul générateur actif à la fois par canal (les
        #: paramètres de consommation, dont le nom de la file, sont
        #: mémorisés sur le canal lui-même) — partager `self._channel`
        #: entre plusieurs files lèverait un ValueError dès la deuxième.
        #:
        #: event_type -> (dedicated channel, consuming generator). One
        #: channel per queue: BlockingChannel.consume() only supports a
        #: single active generator at a time per channel (the
        #: consumption parameters, including the queue name, are
        #: remembered on the channel itself) — sharing `self._channel`
        #: across several queues would raise a ValueError on the
        #: second one.
        self._consumers: dict[str, tuple[Any, Iterator[Any]]] = {}
        #: event_id -> (event_type, canal, delivery_tag, properties).
        #: `channel` est le canal dédié qui a livré ce message: acquitter
        #: ailleurs échouerait, les delivery_tag étant scopés par canal.
        #: `properties` est conservé pour lire son header `x-death` dans
        #: fail().
        #:
        #: event_id -> (event_type, channel, delivery_tag, properties).
        #: `channel` is the dedicated channel that delivered this
        #: message: acknowledging elsewhere would fail, since delivery
        #: tags are scoped per channel. `properties` is kept to read its
        #: `x-death` header in fail().
        self._pending: dict[str, tuple[str, Any, int, pika.BasicProperties]] = {}

    def _connect(self) -> pika.BlockingConnection:
        """Ouvre une connexion bloquante vers le broker AMQP.

        Opens a blocking connection to the AMQP broker.
        """
        return pika.BlockingConnection(pika.URLParameters(self.url))

    def _declare_exchanges(self) -> None:
        """Déclare les trois exchanges partagés (principal, retry, dead-letter).

        Idempotent: une déclaration avec les mêmes paramètres sur un
        exchange existant ne fait rien.

        Declares the three shared exchanges (main, retry, dead-letter).

        Idempotent: declaring with the same parameters on an existing
        exchange is a no-op.
        """
        for exchange in (self.exchange, self.retry_exchange, self.dlq_exchange):
            self._channel.exchange_declare(
                exchange=exchange, exchange_type="direct", durable=True
            )

    def _queue_name(self, event_type: str) -> str:
        """Nom de la file principale associée à ``event_type`` pour ce service.

        Main queue name associated with ``event_type`` for this service.
        """
        return f"{self.prefix}.{self.service_name}.{event_type}"

    def _retry_queue_name(self, event_type: str) -> str:
        """Nom de la file de retry associée à ``event_type``.

        Retry queue name associated with ``event_type``.
        """
        return f"{self._queue_name(event_type)}.retry"

    def _dlq_name(self, event_type: str) -> str:
        """Nom de la file de dead-letter associée à ``event_type``.

        Dead-letter queue name associated with ``event_type``.
        """
        return f"{self._queue_name(event_type)}.dlq"

    def _declare_topology(self, event_type: str) -> str:
        """Déclare et lie la file principale, sa file de retry et sa dead-letter.

        Declares and binds the main queue, its retry queue, and its dead-letter queue.
        """
        queue = self._queue_name(event_type)
        retry_queue = self._retry_queue_name(event_type)
        dlq = self._dlq_name(event_type)

        self._channel.queue_declare(
            queue=queue,
            durable=True,
            arguments={
                "x-dead-letter-exchange": self.retry_exchange,
                "x-dead-letter-routing-key": event_type,
            },
        )
        self._channel.queue_bind(
            queue=queue, exchange=self.exchange, routing_key=event_type
        )

        self._channel.queue_declare(
            queue=retry_queue,
            durable=True,
            arguments={
                "x-message-ttl": self.retry_delay_ms,
                "x-dead-letter-exchange": self.exchange,
                "x-dead-letter-routing-key": event_type,
            },
        )
        self._channel.queue_bind(
            queue=retry_queue, exchange=self.retry_exchange, routing_key=event_type
        )

        self._channel.queue_declare(queue=dlq, durable=True)
        self._channel.queue_bind(
            queue=dlq, exchange=self.dlq_exchange, routing_key=event_type
        )
        return queue

    def publish(self, envelope: EventEnvelope) -> None:
        """Publie ``envelope`` sur l'exchange principal, routé par ``event_type``.

        Publishes ``envelope`` on the main exchange, routed by ``event_type``.
        """
        self._publish_to(self.exchange, envelope.event_type, envelope)

    def _publish_to(
        self, exchange: str, routing_key: str, envelope: EventEnvelope
    ) -> None:
        """Publie ``envelope`` sur ``exchange``, avec quelques tentatives sur coupure.

        Publishes ``envelope`` on ``exchange``, with a few retries on a
        transient network outage.
        """
        body = self.serializer.dumps(envelope)
        properties = pika.BasicProperties(
            content_type="application/json", delivery_mode=2
        )
        attempts = self.publish_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                self._channel.basic_publish(
                    exchange=exchange,
                    routing_key=routing_key,
                    body=body,
                    properties=properties,
                )
                return
            except _TRANSIENT_AMQP_ERRORS:
                if attempt == attempts:
                    raise
                logger.warning(
                    "Publication de %s interrompue (tentative %s/%s), nouvel essai",
                    envelope.event_type,
                    attempt,
                    attempts,
                )
                time.sleep(self.publish_retry_delay * attempt)
                self._reconnect()

    def _reconnect(self) -> None:
        """Rouvre la connexion/le canal AMQP et redéclare les exchanges partagés.

        `BlockingConnection` ne se reconnecte pas seule (contrairement à
        redis-py): après une coupure, il faut explicitement rouvrir la
        connexion avant de retenter une opération.

        Reopens the AMQP connection/channel and redeclares the shared exchanges.

        `BlockingConnection` does not reconnect on its own (unlike
        redis-py): after an outage, the connection must be explicitly
        reopened before retrying an operation.
        """
        # La connexion est déjà en mauvais état: peu importe qu'elle
        # échoue à se fermer proprement.
        with contextlib.suppress(Exception):
            self._connection.close()
        self._connection = self._connect()
        self._channel = self._connection.channel()
        self._declare_exchanges()

    def listen(self, event_types: set[str]) -> Iterator[EventEnvelope]:
        """Déclare la topologie de chaque ``event_type``, renvoie le consommateur.

        Declares each ``event_type``'s topology then returns the
        consuming iterator.
        """
        queues = {
            event_type: self._declare_topology(event_type) for event_type in event_types
        }
        self._consumers = {
            event_type: self._make_consumer(queue)
            for event_type, queue in queues.items()
        }
        return self._consume()

    def _make_consumer(self, queue: str) -> tuple[Any, Iterator[Any]]:
        """Ouvre un canal dédié à ``queue`` et son générateur de consommation.

        Opens a channel dedicated to ``queue`` and its consuming generator.
        """
        channel = self._connection.channel()
        channel.basic_qos(prefetch_count=self.prefetch_count)
        consumer = channel.consume(
            queue, auto_ack=False, inactivity_timeout=self.poll_interval
        )
        return channel, consumer

    def _consume(self) -> Iterator[EventEnvelope]:
        """Parcourt les files en round-robin, yield les messages désérialisables.

        Une coupure réseau pendant la consommation entraîne une
        reconnexion puis la redéclaration de la topologie et des
        consumers: sans ça, le worker planterait sur la première
        coupure au lieu de la traverser comme le fait le backend Redis.

        Round-robins the queues, yields each deserializable application message.

        A network outage during consumption triggers a reconnection
        then redeclares the topology and consumers: without this, the
        worker would crash on the first outage instead of riding it out
        like the Redis backend does.
        """
        while True:
            for event_type, (channel, consumer) in list(self._consumers.items()):
                try:
                    method, properties, body = next(consumer)
                except _TRANSIENT_AMQP_ERRORS as exc:
                    logger.warning(
                        "Connexion RabbitMQ interrompue pendant l'écoute (%s), "
                        "reconnexion",
                        exc,
                    )
                    self._reconnect()
                    queues = {et: self._declare_topology(et) for et in self._consumers}
                    self._consumers = {
                        et: self._make_consumer(queue) for et, queue in queues.items()
                    }
                    break
                if method is None:
                    continue
                envelope = self._to_envelope(
                    event_type, channel, method, properties, body
                )
                if envelope is not None:
                    yield envelope

    def _to_envelope(
        self,
        event_type: str,
        channel: Any,
        method: Any,
        properties: pika.BasicProperties,
        body: bytes,
    ) -> EventEnvelope | None:
        """Désérialise un message, ``None`` (et acquittement) s'il est illisible.

        Deserializes a message, ``None`` (and acknowledged) if unreadable.
        """
        try:
            envelope = self.serializer.loads(body)
        except Exception:
            logger.exception(
                "Message illisible sur %s (delivery_tag=%s) — acquitté sans traitement",
                event_type,
                method.delivery_tag,
            )
            channel.basic_ack(method.delivery_tag)
            return None
        self._pending[envelope.event_id] = (
            event_type,
            channel,
            method.delivery_tag,
            properties,
        )
        return envelope

    def _death_count(self, properties: pika.BasicProperties, queue: str) -> int:
        """Lit, dans le header ``x-death``, le nombre de rejets déjà subis par la file.

        RabbitMQ incrémente lui-même cette entrée à chaque `nack` vers
        la dead-letter-exchange depuis la même file: contrairement au
        compteur `x-retry-count` du backend Kafka, il n'y a rien à
        maintenir manuellement ici.

        Reads, from the ``x-death`` header, how many times the queue
        has already rejected this message.

        RabbitMQ increments this entry itself on every `nack` to the
        dead-letter-exchange from the same queue: unlike the Kafka
        backend's `x-retry-count` counter, there is nothing to maintain
        manually here.
        """
        headers = properties.headers or {}
        for death in headers.get("x-death", []):
            if death.get("queue") == queue and death.get("reason") == "rejected":
                return int(death.get("count", 0))
        return 0

    def ack(self, envelope: EventEnvelope) -> None:
        """Acquitte ``envelope`` auprès de RabbitMQ.

        Acknowledges ``envelope`` with RabbitMQ.
        """
        entry = self._pending.pop(envelope.event_id, None)
        if entry is None:
            return
        _, channel, delivery_tag, _ = entry
        channel.basic_ack(delivery_tag)

    def fail(self, envelope: EventEnvelope) -> bool:
        """Retente (via la file de retry) ou déplace ``envelope`` en dead-letter.

        Retries (via the retry queue) or moves ``envelope`` to dead-letter.
        """
        entry = self._pending.pop(envelope.event_id, None)
        if entry is None:
            return True
        event_type, channel, delivery_tag, properties = entry
        queue = self._queue_name(event_type)
        attempt = self._death_count(properties, queue) + 1

        if attempt < self.max_retries:
            logger.warning(
                "Échec de traitement de %s (%s), tentative %s/%s — sera retenté",
                envelope.event_type,
                envelope.event_id,
                attempt,
                self.max_retries,
            )
            channel.basic_nack(delivery_tag, requeue=False)
            return False

        logger.error(
            "Échec définitif de %s (%s) après %s tentatives — dead-letter",
            envelope.event_type,
            envelope.event_id,
            attempt,
        )
        # Publie en dead-letter puis acquitte l'original: si le worker
        # meurt entre les deux, le message reste non acquitté sur la
        # file principale et sera redistribué plutôt que perdu, au prix
        # d'un doublon possible en dead-letter à la reprise — même
        # compromis que le MULTI/EXEC du backend Redis.
        #
        # Publishes to dead-letter then acknowledges the original: if
        # the worker dies between the two, the message stays
        # unacknowledged on the main queue and will be redelivered
        # rather than lost, at the cost of a possible duplicate in
        # dead-letter on the next attempt — same trade-off as the Redis
        # backend's MULTI/EXEC.
        self._publish_to(self.dlq_exchange, event_type, envelope)
        channel.basic_ack(delivery_tag)
        return True

    def close(self) -> None:
        """Ferme les canaux (consumers + principal) puis la connexion AMQP.

        Closes the channels (consumers + main) then the AMQP connection.
        """
        try:
            for channel, _ in self._consumers.values():
                with contextlib.suppress(Exception):
                    channel.close()
            self._channel.close()
        finally:
            self._connection.close()
