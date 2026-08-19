import json

import pytest
from django.test import RequestFactory, override_settings

from django_event_bus.exceptions import ImproperlyConfiguredError
from django_event_bus.remote import ResourceSerializer, expose_resource
from django_event_bus.remote.resources import (
    get_registered_serializer,
    registry_resolver,
)
from django_event_bus.remote.views import resource_detail
from tests.testapp.models import Widget, WidgetOwner


@pytest.fixture(autouse=True)
def _reset_resource_registry():
    from django_event_bus.remote.resources import reset_registry

    reset_registry()
    yield
    reset_registry()


def _unique_resource_name(label: str) -> str:
    # Chaque test enregistre sa propre ressource pour ne pas entrer en
    # collision avec les autres via le registre partagé.
    return f"widgets.{label}"


def test_expose_resource_requires_model_and_resource():
    class Incomplete(ResourceSerializer):
        class Meta:
            pass

    with pytest.raises(ImproperlyConfiguredError):
        expose_resource(Incomplete)


def test_expose_resource_rejects_duplicate_resource_name_from_different_class():
    resource_name = _unique_resource_name("dup")

    @expose_resource
    class FirstSerializer(ResourceSerializer):
        class Meta:
            model = Widget
            resource = resource_name
            fields = ["id"]

    class SecondSerializer(ResourceSerializer):
        class Meta:
            model = Widget
            resource = resource_name
            fields = ["id"]

    with pytest.raises(ImproperlyConfiguredError):
        expose_resource(SecondSerializer)


def test_expose_resource_is_idempotent_for_the_same_class():
    resource_name = _unique_resource_name("idempotent")

    class MySerializer(ResourceSerializer):
        class Meta:
            model = Widget
            resource = resource_name
            fields = ["id"]

    expose_resource(MySerializer)
    expose_resource(MySerializer)  # ré-import: ne doit pas lever

    assert get_registered_serializer(resource_name) is MySerializer


@pytest.mark.django_db
def test_fields_all_includes_every_model_field():
    resource_name = _unique_resource_name("all_fields")

    @expose_resource
    class WidgetSerializer(ResourceSerializer):
        class Meta:
            model = Widget
            resource = resource_name
            # fields = "__all__" par défaut

    widget = Widget.objects.create(name="Gadget", price_cents=1500)

    assert WidgetSerializer(widget).data == {
        "id": widget.id,
        "name": "Gadget",
        "price_cents": 1500,
    }


@pytest.mark.django_db
def test_explicit_fields_list_restricts_output():
    resource_name = _unique_resource_name("explicit_fields")

    @expose_resource
    class WidgetSerializer(ResourceSerializer):
        class Meta:
            model = Widget
            resource = resource_name
            fields = ["name"]

    widget = Widget.objects.create(name="Gadget", price_cents=1500)

    assert WidgetSerializer(widget).data == {"name": "Gadget"}


@pytest.mark.django_db
def test_exclude_removes_listed_fields_from_all():
    resource_name = _unique_resource_name("exclude")

    @expose_resource
    class WidgetSerializer(ResourceSerializer):
        class Meta:
            model = Widget
            resource = resource_name
            exclude = ["price_cents"]

    widget = Widget.objects.create(name="Gadget", price_cents=1500)

    assert WidgetSerializer(widget).data == {"id": widget.id, "name": "Gadget"}


def test_fields_and_exclude_together_is_rejected():
    resource_name = _unique_resource_name("both")

    @expose_resource
    class WidgetSerializer(ResourceSerializer):
        class Meta:
            model = Widget
            resource = resource_name
            fields = ["name"]
            exclude = ["price_cents"]

    with pytest.raises(ImproperlyConfiguredError):
        WidgetSerializer.get_fields()


@pytest.mark.django_db
def test_get_field_method_computes_a_derived_value():
    resource_name = _unique_resource_name("computed")

    @expose_resource
    class WidgetSerializer(ResourceSerializer):
        class Meta:
            model = Widget
            resource = resource_name
            fields = ["name", "price_display"]

        def get_price_display(self, instance):
            return f"{instance.price_cents / 100:.2f} EUR"

    widget = Widget.objects.create(name="Gadget", price_cents=1500)

    assert WidgetSerializer(widget).data == {
        "name": "Gadget",
        "price_display": "15.00 EUR",
    }


def test_expose_resource_rejects_relation_field_without_getter_at_registration_time():
    """Détecté au chargement, pas à la première requête HTTP/gRPC (cf.
    ``resources._check_no_unserializable_relation_fields``)."""
    resource_name = _unique_resource_name("relation_field")

    class OwnerSerializer(ResourceSerializer):
        class Meta:
            model = WidgetOwner
            resource = resource_name
            fields = ["id", "widget"]

    with pytest.raises(ImproperlyConfiguredError, match="get_widget"):
        expose_resource(OwnerSerializer)

    # L'échec de validation ne doit pas laisser la ressource enregistrée.
    assert get_registered_serializer(resource_name) is None


def test_expose_resource_allows_relation_field_with_getter():
    resource_name = _unique_resource_name("relation_field_with_getter")

    @expose_resource
    class OwnerSerializer(ResourceSerializer):
        class Meta:
            model = WidgetOwner
            resource = resource_name
            fields = ["id", "widget"]

        def get_widget(self, instance):
            return instance.widget_id

    assert get_registered_serializer(resource_name) is OwnerSerializer


def test_expose_resource_skips_relation_validation_when_fields_and_exclude_conflict():
    """La validation fields/exclude reste signalée à l'usage (get_fields()),
    pas à la décoration — comportement inchangé, voir le test ci-dessus
    dans la classe existante."""
    resource_name = _unique_resource_name("relation_field_conflict")

    @expose_resource
    class OwnerSerializer(ResourceSerializer):
        class Meta:
            model = WidgetOwner
            resource = resource_name
            fields = ["widget"]
            exclude = ["id"]

    with pytest.raises(ImproperlyConfiguredError):
        OwnerSerializer.get_fields()


@pytest.mark.django_db
def test_missing_field_without_get_method_raises_a_clear_error():
    resource_name = _unique_resource_name("missing_field")

    @expose_resource
    class WidgetSerializer(ResourceSerializer):
        class Meta:
            model = Widget
            resource = resource_name
            fields = ["does_not_exist"]

    widget = Widget.objects.create(name="Gadget", price_cents=1500)

    with pytest.raises(ImproperlyConfiguredError, match="get_does_not_exist"):
        _ = WidgetSerializer(widget).data


@pytest.mark.django_db
def test_to_representation_override_gives_full_control():
    resource_name = _unique_resource_name("override_repr")

    @expose_resource
    class WidgetSerializer(ResourceSerializer):
        class Meta:
            model = Widget
            resource = resource_name

        def to_representation(self, instance):
            return {"label": instance.name.upper()}

    widget = Widget.objects.create(name="Gadget", price_cents=1500)

    assert WidgetSerializer(widget).data == {"label": "GADGET"}


@pytest.mark.django_db
def test_get_queryset_override_restricts_visibility():
    resource_name = _unique_resource_name("scoped_queryset")

    @expose_resource
    class CheapWidgetSerializer(ResourceSerializer):
        class Meta:
            model = Widget
            resource = resource_name
            fields = ["id", "name"]

        @classmethod
        def get_queryset(cls):
            return Widget.objects.filter(price_cents__lt=1000)

    cheap = Widget.objects.create(name="Cheap", price_cents=500)
    pricey = Widget.objects.create(name="Pricey", price_cents=5000)

    assert registry_resolver(resource_name, str(cheap.id)) == {
        "id": cheap.id,
        "name": "Cheap",
    }
    # Hors du get_queryset() restreint: absent, pas une erreur.
    assert registry_resolver(resource_name, str(pricey.id)) is None


@pytest.mark.django_db
def test_registry_resolver_end_to_end():
    resource_name = _unique_resource_name("resolver")

    @expose_resource
    class WidgetSerializer(ResourceSerializer):
        class Meta:
            model = Widget
            resource = resource_name
            fields = ["id", "name"]

    widget = Widget.objects.create(name="Gadget", price_cents=1500)

    assert registry_resolver(resource_name, str(widget.id)) == {
        "id": widget.id,
        "name": "Gadget",
    }
    assert registry_resolver(resource_name, "not-a-real-id") is None
    assert registry_resolver("nobody.exposes.this", "1") is None


@pytest.mark.django_db
def test_resource_detail_view_end_to_end():
    resource_name = _unique_resource_name("http_view")

    @expose_resource
    class WidgetSerializer(ResourceSerializer):
        class Meta:
            model = Widget
            resource = resource_name
            fields = ["id", "name"]

    widget = Widget.objects.create(name="Gadget", price_cents=1500)
    factory = RequestFactory()

    ok = resource_detail(factory.get("/"), resource_name, str(widget.id))
    assert ok.status_code == 200
    assert json.loads(ok.content) == {"id": widget.id, "name": "Gadget"}

    not_found_pk = resource_detail(factory.get("/"), resource_name, "999999")
    assert not_found_pk.status_code == 404

    malformed_pk = resource_detail(factory.get("/"), resource_name, "not-an-int")
    assert malformed_pk.status_code == 404

    unknown_resource = resource_detail(factory.get("/"), "nobody.exposes.this", "1")
    assert unknown_resource.status_code == 404


def test_resource_detail_rejects_non_get_methods():
    resource_name = _unique_resource_name("method_not_allowed")

    @expose_resource
    class WidgetSerializer(ResourceSerializer):
        class Meta:
            model = Widget
            resource = resource_name
            fields = ["id"]

    factory = RequestFactory()

    response = resource_detail(factory.post("/"), resource_name, "1")

    assert response.status_code == 405


@pytest.mark.django_db
def test_resource_detail_without_auth_token_configured_is_unrestricted():
    """Comportement par défaut inchangé: AUTH_TOKEN non défini -> pas de contrôle."""
    resource_name = _unique_resource_name("no_auth_configured")

    @expose_resource
    class WidgetSerializer(ResourceSerializer):
        class Meta:
            model = Widget
            resource = resource_name
            fields = ["id"]

    widget = Widget.objects.create(name="Gadget", price_cents=1500)
    factory = RequestFactory()

    response = resource_detail(factory.get("/"), resource_name, str(widget.id))

    assert response.status_code == 200


@pytest.mark.django_db
def test_resource_detail_requires_matching_bearer_token_when_configured():
    resource_name = _unique_resource_name("auth_required")

    @expose_resource
    class WidgetSerializer(ResourceSerializer):
        class Meta:
            model = Widget
            resource = resource_name
            fields = ["id"]

    widget = Widget.objects.create(name="Gadget", price_cents=1500)
    factory = RequestFactory()

    with override_settings(REMOTE_DATA={"AUTH_TOKEN": "s3cr3t"}):
        missing = resource_detail(factory.get("/"), resource_name, str(widget.id))
        assert missing.status_code == 401

        wrong = resource_detail(
            factory.get("/", HTTP_AUTHORIZATION="Bearer nope"),
            resource_name,
            str(widget.id),
        )
        assert wrong.status_code == 401

        correct = resource_detail(
            factory.get("/", HTTP_AUTHORIZATION="Bearer s3cr3t"),
            resource_name,
            str(widget.id),
        )
        assert correct.status_code == 200


@pytest.mark.django_db
def test_resource_detail_rate_limits_by_remote_addr():
    resource_name = _unique_resource_name("rate_limited")

    @expose_resource
    class WidgetSerializer(ResourceSerializer):
        class Meta:
            model = Widget
            resource = resource_name
            fields = ["id"]

    widget = Widget.objects.create(name="Gadget", price_cents=1500)
    factory = RequestFactory()

    with override_settings(
        REMOTE_DATA={"RATE_LIMIT": {"LIMIT": 1, "WINDOW_SECONDS": 60}}
    ):
        first = resource_detail(
            factory.get("/", REMOTE_ADDR="10.0.0.1"), resource_name, str(widget.id)
        )
        assert first.status_code == 200

        second = resource_detail(
            factory.get("/", REMOTE_ADDR="10.0.0.1"), resource_name, str(widget.id)
        )
        assert second.status_code == 429

        # Un autre appelant garde son propre budget.
        other_caller = resource_detail(
            factory.get("/", REMOTE_ADDR="10.0.0.2"), resource_name, str(widget.id)
        )
        assert other_caller.status_code == 200


@pytest.mark.django_db
def test_resource_detail_rate_limit_disabled_when_none():
    resource_name = _unique_resource_name("rate_limit_disabled")

    @expose_resource
    class WidgetSerializer(ResourceSerializer):
        class Meta:
            model = Widget
            resource = resource_name
            fields = ["id"]

    widget = Widget.objects.create(name="Gadget", price_cents=1500)
    factory = RequestFactory()

    with override_settings(REMOTE_DATA={"RATE_LIMIT": None}):
        for _ in range(5):
            response = resource_detail(
                factory.get("/", REMOTE_ADDR="10.0.0.3"), resource_name, str(widget.id)
            )
            assert response.status_code == 200
