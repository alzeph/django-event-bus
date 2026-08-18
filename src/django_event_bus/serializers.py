from __future__ import annotations

import json
from typing import Any

from django.core.serializers.json import DjangoJSONEncoder

from .envelope import EventEnvelope


class JSONEventSerializer:
    """Sérialiseur par défaut. Réutilise DjangoJSONEncoder (déjà capable
    d'encoder UUID, Decimal, date/datetime) plutôt que d'en réécrire un.
    """

    def dumps(self, envelope: EventEnvelope) -> bytes:
        return json.dumps(envelope.to_dict(), cls=DjangoJSONEncoder).encode("utf-8")

    def loads(self, data: bytes | str) -> EventEnvelope:
        raw: dict[str, Any] = json.loads(data)
        return EventEnvelope.from_dict(raw)
