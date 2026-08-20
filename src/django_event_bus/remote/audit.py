"""Journal d'audit structuré des accès aux ressources distantes exposées.

Un seul logger, nommé pareil pour les deux transports
(``django_event_bus.remote.audit``), pour qu'un opérateur puisse router
ou filtrer ces entrées indépendamment des logs applicatifs — accès
refusés (auth, rate limit) en ``WARNING``, accès accordés en ``INFO``.

Structured audit trail for exposed remote-resource access attempts.

One logger, named the same for both transports
(``django_event_bus.remote.audit``), so an operator can route or filter
these entries independently from application logs — denied accesses
(auth, rate limit) at ``WARNING``, granted ones at ``INFO``.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("django_event_bus.remote.audit")


def log_access(
    *,
    transport: str,
    granted: bool,
    peer: str | None,
    resource: str | None = None,
    pk: str | None = None,
    caller: str | None = None,
    reason: str | None = None,
) -> None:
    """Journalise une tentative d'accès (accordée ou refusée) à une ressource exposée.

    Les champs sont aussi passés via ``extra`` (préfixés
    ``event_bus_audit_``) pour être exploitables par un pipeline de logs
    structuré (JSON) sans avoir à parser le message.

    Logs an access attempt (granted or denied) to an exposed resource.

    Fields are also passed via ``extra`` (prefixed ``event_bus_audit_``)
    so a structured (JSON) log pipeline can consume them without parsing
    the message.
    """
    level = logging.INFO if granted else logging.WARNING
    logger.log(
        level,
        "%s access %s: resource=%s pk=%s caller=%s peer=%s%s",
        transport,
        "granted" if granted else "denied",
        resource or "-",
        pk or "-",
        caller or "-",
        peer or "-",
        f" reason={reason}" if reason else "",
        extra={
            "event_bus_audit_transport": transport,
            "event_bus_audit_granted": granted,
            "event_bus_audit_resource": resource,
            "event_bus_audit_pk": pk,
            "event_bus_audit_caller": caller,
            "event_bus_audit_peer": peer,
            "event_bus_audit_reason": reason,
        },
    )
