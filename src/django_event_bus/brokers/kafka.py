"""Backend Kafka du bus d'événements.

Kafka backend for the event bus.
"""

from __future__ import annotations

import logging
import os
import socket
from collections.abc import Iterator
from typing import Any, cast

from confluent_kafka import Consumer, KafkaError, KafkaException, Message, Producer
from confluent_kafka.admin import AdminClient, NewTopic

from ..envelope import EventEnvelope
from ..exceptions import BrokerError
from ..serializers import JSONEventSerializer
from .base import BaseBroker

logger = logging.getLogger("django_event_bus.kafka")

#: Header portant le nombre de tentatives déjà effectuées pour un message,
#: incrémenté à chaque republication par fail(). Kafka ne proposant pas de
#: nack()/redelivery par message (contrairement à Redis XPENDING ou aux
#: files RabbitMQ), c'est le seul moyen de faire survivre ce compteur à un
#: redémarrage du worker.
#:
#: Header carrying the number of attempts already made for a message,
#: incremented on each republish by fail(). Since Kafka has no
#: per-message nack()/redelivery (unlike Redis XPENDING or RabbitMQ
#: queues), this is the only way to make this counter survive a worker
#: restart.
_RETRY_HEADER = "x-retry-count"


class KafkaBroker(BaseBroker):
    """Backend Kafka basé sur les consumer groups + republication pour les retries.

    Un topic par `event_type` (`{TOPIC_PREFIX}.{event_type}`), un
    consumer group par service (`GROUP_ID`, par défaut `SERVICE_NAME`)
    pour un offset de lecture indépendant par service — comme le backend
    Redis Streams. `AUTO_OFFSET_RESET="earliest"` par défaut: un nouveau
    consumer group rejoue tout l'historique du topic, pour la même
    raison que Redis Streams crée son groupe à `start_id="0"`.

    Kafka ne proposant pas de nack()/redelivery natif par message,
    `fail()` republie l'événement (header `x-retry-count` incrémenté)
    sur le même topic tant que `MAX_RETRIES` n'est pas atteint, puis le
    déplace vers `{topic}.dlq` — l'équivalent du stream `:dlq` de Redis.

    `listen()` crée (via `AdminClient`) les topics manquants avant de
    s'y abonner, comme `_ensure_group()` le fait côté Redis pour son
    stream: sans ça, un topic inexistant au moment du `subscribe()`
    n'est découvert par le consumer qu'au prochain rafraîchissement de
    métadonnées de librdkafka (jusqu'à 5 minutes par défaut), même une
    fois auto-créé côté broker par un `produce()` — et pas du tout si
    l'auto-création de topics est désactivée côté cluster (fréquent en
    production).

    Options reconnues (`EVENT_BUS["OPTIONS"]`):
        BOOTSTRAP_SERVERS: liste de brokers Kafka, séparés par des
            virgules (défaut "localhost:9092")
        TOPIC_PREFIX: préfixe des noms de topic (défaut "eventbus")
        GROUP_ID: consumer group (défaut: SERVICE_NAME)
        MAX_RETRIES: tentatives avant dead-letter (défaut 3)
        POLL_TIMEOUT: durée de chaque poll() en secondes (défaut 1.0)
        AUTO_OFFSET_RESET: position de départ si aucun offset committé
            (défaut "earliest")
        CLIENT_ID: identifiant du client (défaut auto:
            "{hostname}-{pid}")
        NUM_PARTITIONS: nombre de partitions des topics créés par
            `listen()` (défaut 1)
        REPLICATION_FACTOR: facteur de réplication des topics créés par
            `listen()` (défaut 1 — à augmenter en production)
        PUBLISH_RETRIES: tentatives supplémentaires si produce() essuie
            un `BufferError` (file locale du producer pleine, défaut 2)
        PUBLISH_RETRY_DELAY: délai de base (secondes) entre ces
            tentatives, multiplié par le numéro de la tentative (défaut
            0.2)
        PRODUCER_CONFIG: dict de configuration confluent-kafka
            additionnelle pour le producer (TLS, SASL, ...), fusionné
            par-dessus les options ci-dessus
        CONSUMER_CONFIG: idem pour le consumer

    Kafka backend based on consumer groups + republishing for retries.

    One topic per `event_type` (`{TOPIC_PREFIX}.{event_type}`), one
    consumer group per service (`GROUP_ID`, defaults to `SERVICE_NAME`)
    for an independent read offset per service — like the Redis Streams
    backend. `AUTO_OFFSET_RESET="earliest"` by default: a brand new
    consumer group replays the topic's full history, for the same
    reason Redis Streams creates its group at `start_id="0"`.

    Since Kafka has no native per-message nack()/redelivery, `fail()`
    republishes the event (with an incremented `x-retry-count` header)
    on the same topic until `MAX_RETRIES` is reached, then moves it to
    `{topic}.dlq` — the equivalent of Redis's `:dlq` stream.

    `listen()` creates (via `AdminClient`) any missing topics before
    subscribing to them, like Redis's `_ensure_group()` does for its
    stream: without this, a topic that doesn't exist yet at
    `subscribe()` time is only discovered by the consumer on
    librdkafka's next metadata refresh (up to 5 minutes by default),
    even once auto-created broker-side by a `produce()` — and not at
    all if topic auto-creation is disabled cluster-side (common in
    production).

    Recognized options (`EVENT_BUS["OPTIONS"]`):
        BOOTSTRAP_SERVERS: comma-separated list of Kafka brokers
            (default "localhost:9092")
        TOPIC_PREFIX: topic name prefix (default "eventbus")
        GROUP_ID: consumer group (default: SERVICE_NAME)
        MAX_RETRIES: attempts before dead-letter (default 3)
        POLL_TIMEOUT: duration of each poll() in seconds (default 1.0)
        AUTO_OFFSET_RESET: starting position when no offset has been
            committed yet (default "earliest")
        CLIENT_ID: client identifier (default auto:
            "{hostname}-{pid}")
        NUM_PARTITIONS: partition count for topics created by
            `listen()` (default 1)
        REPLICATION_FACTOR: replication factor for topics created by
            `listen()` (default 1 — raise it in production)
        PUBLISH_RETRIES: extra attempts if produce() hits a
            `BufferError` (producer's local queue full, default 2)
        PUBLISH_RETRY_DELAY: base delay (seconds) between those
            attempts, multiplied by the attempt number (default 0.2)
        PRODUCER_CONFIG: additional confluent-kafka configuration dict
            for the producer (TLS, SASL, ...), merged on top of the
            options above
        CONSUMER_CONFIG: same for the consumer
    """

    def __init__(self, *, service_name: str, options: dict) -> None:
        """Configure le producer et les paramètres du consumer.

        Configures the producer and the consumer parameters, reads the
        options above.
        """
        super().__init__(service_name=service_name, options=options)
        self.bootstrap_servers = options.get("BOOTSTRAP_SERVERS", "localhost:9092")
        self.prefix = options.get("TOPIC_PREFIX", "eventbus")
        self.group_id = options.get("GROUP_ID", service_name)
        self.max_retries = int(options.get("MAX_RETRIES", 3))
        self.poll_timeout = float(options.get("POLL_TIMEOUT", 1.0))
        self.auto_offset_reset = options.get("AUTO_OFFSET_RESET", "earliest")
        default_client_id = f"{socket.gethostname()}-{os.getpid()}"
        self.client_id = options.get("CLIENT_ID", default_client_id)
        self.num_partitions = int(options.get("NUM_PARTITIONS", 1))
        self.replication_factor = int(options.get("REPLICATION_FACTOR", 1))
        self.publish_retries = int(options.get("PUBLISH_RETRIES", 2))
        self.publish_retry_delay = float(options.get("PUBLISH_RETRY_DELAY", 0.2))
        self.serializer = JSONEventSerializer()

        self._admin = AdminClient({"bootstrap.servers": self.bootstrap_servers})
        self._producer = Producer(
            {
                "bootstrap.servers": self.bootstrap_servers,
                "client.id": self.client_id,
                **options.get("PRODUCER_CONFIG", {}),
            }
        )
        self._consumer_config: dict[str, Any] = {
            "bootstrap.servers": self.bootstrap_servers,
            "group.id": self.group_id,
            "client.id": self.client_id,
            "enable.auto.commit": False,
            "auto.offset.reset": self.auto_offset_reset,
            **options.get("CONSUMER_CONFIG", {}),
        }
        self._consumer: Consumer | None = None
        self._pending: dict[str, Message] = {}

    def _topic_name(self, event_type: str) -> str:
        """Nom du topic Kafka associé à ``event_type``.

        Kafka topic name associated with ``event_type``.
        """
        return f"{self.prefix}.{event_type}"

    def _dlq_name(self, event_type: str) -> str:
        """Nom du topic de dead-letter associé à ``event_type``.

        Dead-letter topic name associated with ``event_type``.
        """
        return f"{self._topic_name(event_type)}.dlq"

    def publish(self, envelope: EventEnvelope) -> None:
        """Publie ``envelope`` sur son topic, avec un compteur de tentatives à zéro.

        Publishes ``envelope`` on its topic, with a retry counter at zero.
        """
        self._produce(self._topic_name(envelope.event_type), envelope, retry_count=0)

    def _produce(
        self, topic: str, envelope: EventEnvelope, *, retry_count: int
    ) -> None:
        """Produit ``envelope`` sur ``topic`` et attend sa confirmation de livraison.

        `flush()` rend l'appel synchrone (comme XADD côté Redis): un
        `publish()` qui retourne garantit que le message a atteint le
        broker Kafka, pas seulement la file locale du producer.

        Produces ``envelope`` on ``topic`` and waits for its delivery confirmation.

        `flush()` makes the call synchronous (like XADD on the Redis
        side): a `publish()` that returns guarantees the message
        reached the Kafka broker, not just the producer's local queue.
        """
        data = self.serializer.dumps(envelope)
        headers: list[tuple[str, str | bytes | None]] = [
            (_RETRY_HEADER, str(retry_count).encode())
        ]
        delivery_error: KafkaError | None = None

        def _on_delivery(err: KafkaError | None, _msg: Message) -> None:
            nonlocal delivery_error
            delivery_error = err

        attempts = self.publish_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                self._producer.produce(
                    topic, value=data, headers=headers, on_delivery=_on_delivery
                )
                break
            except BufferError:
                if attempt == attempts:
                    raise
                logger.warning(
                    "File locale du producer Kafka pleine (tentative %s/%s), "
                    "nouvel essai",
                    attempt,
                    attempts,
                )
                self._producer.poll(self.publish_retry_delay * attempt)

        self._producer.flush(10)
        if delivery_error is not None:
            raise BrokerError(f"Échec de publication sur {topic}: {delivery_error}")

    def listen(self, event_types: set[str]) -> Iterator[EventEnvelope]:
        """Crée les topics manquants, souscrit, renvoie l'itérateur de consommation.

        Creates any missing topics, subscribes, then returns the
        consuming iterator.
        """
        topics = [self._topic_name(event_type) for event_type in event_types]
        dlq_topics = [self._dlq_name(event_type) for event_type in event_types]
        self._ensure_topics(topics + dlq_topics)
        self._consumer = Consumer(self._consumer_config)
        self._consumer.subscribe(topics)
        return self._consume()

    def _ensure_topics(self, topics: list[str]) -> None:
        """Crée les ``topics`` manquants, ignore ceux qui existent déjà.

        Creates the missing ``topics``, ignores the ones that already exist.
        """
        new_topics = [
            NewTopic(
                topic,
                num_partitions=self.num_partitions,
                replication_factor=self.replication_factor,
            )
            for topic in topics
        ]
        futures = self._admin.create_topics(new_topics)
        for future in futures.values():
            try:
                future.result()
            except KafkaException as exc:
                if exc.args[0].code() != KafkaError.TOPIC_ALREADY_EXISTS:
                    raise

    def _consume(self) -> Iterator[EventEnvelope]:
        """Poll en boucle, yield chaque message applicatif désérialisable.

        Polling loop, yields each deserializable application message.
        """
        assert self._consumer is not None
        while True:
            msg = self._consumer.poll(self.poll_timeout)
            if msg is None:
                continue
            error = msg.error()
            if error is not None:
                if error.code() == KafkaError._PARTITION_EOF:
                    continue
                logger.warning(
                    "Erreur Kafka pendant l'écoute (%s), nouvelle tentative", error
                )
                continue
            envelope = self._to_envelope(msg)
            if envelope is not None:
                yield envelope

    def _to_envelope(self, msg: Message) -> EventEnvelope | None:
        """Désérialise un message, ``None`` (et commit) s'il est illisible.

        Message illisible (schéma incompatible, corruption, ...): son
        offset est committé pour ne pas bloquer le worker en boucle sur
        un message qu'il ne pourra jamais traiter avec succès.

        Deserializes a message, ``None`` (and commit) if unreadable.

        Unreadable message (incompatible schema, corruption, ...): its
        offset is committed so as not to block the worker in a loop on
        a message it could never process successfully.
        """
        try:
            envelope = self.serializer.loads(msg.value() or b"")
        except Exception:
            logger.exception(
                "Message illisible sur %s (offset=%s) — committé sans traitement",
                msg.topic(),
                msg.offset(),
            )
            assert self._consumer is not None
            self._consumer.commit(message=msg, asynchronous=False)
            return None
        self._pending[envelope.event_id] = msg
        return envelope

    def _retry_count(self, msg: Message) -> int:
        """Lit le nombre de tentatives déjà effectuées (header ``x-retry-count``).

        Reads the number of attempts already made from the
        ``x-retry-count`` header.
        """
        # confluent-kafka type ``headers()`` en Dict | List (forme aussi
        # acceptée en entrée par produce()), mais ne renvoie jamais que
        # des listes de tuples: la forme réellement produite ici, dans
        # `_produce()` ci-dessus.
        #
        # confluent-kafka types ``headers()`` as Dict | List (also the
        # form accepted as input by produce()), but only ever returns
        # lists of tuples: the actual shape produced here, in
        # `_produce()` above.
        headers = cast("list[tuple[str, str | bytes | None]]", msg.headers() or [])
        for key, value in headers:
            if key == _RETRY_HEADER and isinstance(value, bytes):
                return int(value.decode())
        return 0

    def ack(self, envelope: EventEnvelope) -> None:
        """Committe l'offset de ``envelope`` auprès de Kafka.

        Commits ``envelope``'s offset with Kafka.
        """
        msg = self._pending.pop(envelope.event_id, None)
        if msg is None:
            return
        assert self._consumer is not None
        self._consumer.commit(message=msg, asynchronous=False)

    def fail(self, envelope: EventEnvelope) -> bool:
        """Retente (republication) ou déplace ``envelope`` en dead-letter.

        Retries (republish) or moves ``envelope`` to dead-letter
        depending on the counter.
        """
        msg = self._pending.pop(envelope.event_id, None)
        if msg is None:
            return True
        assert self._consumer is not None

        attempt = self._retry_count(msg) + 1

        if attempt < self.max_retries:
            logger.warning(
                "Échec de traitement de %s (%s), tentative %s/%s — sera retenté",
                envelope.event_type,
                envelope.event_id,
                attempt,
                self.max_retries,
            )
            self._produce(
                self._topic_name(envelope.event_type), envelope, retry_count=attempt
            )
            self._consumer.commit(message=msg, asynchronous=False)
            return False

        logger.error(
            "Échec définitif de %s (%s) après %s tentatives — dead-letter",
            envelope.event_type,
            envelope.event_id,
            attempt,
        )
        self._produce(
            self._dlq_name(envelope.event_type), envelope, retry_count=attempt
        )
        self._consumer.commit(message=msg, asynchronous=False)
        return True

    def close(self) -> None:
        """Vide le producer puis ferme le consumer.

        Flushes the producer then closes the consumer.
        """
        self._producer.flush(10)
        if self._consumer is not None:
            self._consumer.close()
