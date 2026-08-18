#!/usr/bin/env python
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "service_auth.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Impossible d'importer Django. Lancez ce script avec "
            "`uv run python example/service_auth/manage.py ...` depuis la "
            "racine du dépôt django-event-bus."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
