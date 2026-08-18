"""Enveloppe d'événement transportée sur le bus.

Event envelope carried on the bus.
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime
from typing import Any


@dataclasses.dataclass(frozen=True)
class EventEnvelope:
    """Unité de transport d'un événement sur le bus.

    `event_type` suit la convention "{service_émetteur}.{nom_événement}"
    (ex: "auth.user_created") pour éviter les collisions entre services.

    Transport unit of an event on the bus.

    `event_type` follows the "{source_service}.{event_name}" convention
    (e.g. "auth.user_created") to avoid collisions between services.
    """

    event_type: str
    source_service: str
    payload: dict[str, Any]
    event_id: str = dataclasses.field(default_factory=lambda: str(uuid.uuid4()))
    occurred_at: datetime = dataclasses.field(default_factory=lambda: datetime.now(UTC))
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        """Sérialise l'enveloppe en dict prêt pour l'encodage JSON.

        Serializes the envelope into a dict ready for JSON encoding.
        """
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "source_service": self.source_service,
            "payload": self.payload,
            "occurred_at": self.occurred_at.isoformat(),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EventEnvelope:
        """Reconstruit une enveloppe à partir d'un dict issu de ``to_dict``.

        Rebuilds an envelope from a dict produced by ``to_dict``.
        """
        return cls(
            event_id=data["event_id"],
            event_type=data["event_type"],
            source_service=data["source_service"],
            payload=data["payload"],
            occurred_at=datetime.fromisoformat(data["occurred_at"]),
            version=int(data.get("version", 1)),
        )
