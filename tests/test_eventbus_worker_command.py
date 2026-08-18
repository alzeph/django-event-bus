import io
from unittest.mock import patch

from django.core.management import call_command


def test_worker_exits_immediately_when_no_receiver_registered():
    """Sans @receiver enregistré, la commande doit avertir et s'arrêter
    tout de suite plutôt que de bloquer sur un listen() sans intérêt.

    Le registre global n'est jamais vidé entre tests (l'autodiscovery ne
    doit tourner qu'une fois par process), donc `registered_event_types`
    n'est en pratique jamais vide ici: on le simule explicitement plutôt
    que de dépendre de l'ordre d'exécution des tests.
    """
    target = (
        "django_event_bus.management.commands.eventbus_worker.registered_event_types"
    )
    with patch(target, return_value=set()):
        out = io.StringIO()
        call_command("eventbus_worker", stdout=out)

    assert "Aucun @receiver enregistré" in out.getvalue()
