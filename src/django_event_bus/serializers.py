"""Sérialisation des enveloppes d'événement.

Event envelope serialization.
"""

from __future__ import annotations

import json
from typing import Any

from django.core.serializers.json import DjangoJSONEncoder

from .envelope import EventEnvelope


class JSONEventSerializer:
    """Sérialiseur par défaut.

    Réutilise ``DjangoJSONEncoder`` (déjà capable d'encoder UUID,
    Decimal, date/datetime) plutôt que d'en réécrire un.

    Default serializer.

    Reuses ``DjangoJSONEncoder`` (already able to encode UUID, Decimal,
    date/datetime) instead of writing a new one.
    """

    def dumps(self, envelope: EventEnvelope) -> bytes:
        """Encode l'enveloppe en JSON UTF-8.

        Encodes the envelope as UTF-8 JSON.
        """
        return json.dumps(envelope.to_dict(), cls=DjangoJSONEncoder).encode("utf-8")

    def loads(self, data: bytes | str) -> EventEnvelope:
        """Décode une enveloppe depuis du JSON.

        Decodes an envelope from JSON.
        """
        raw: dict[str, Any] = json.loads(data)
        return EventEnvelope.from_dict(raw)
