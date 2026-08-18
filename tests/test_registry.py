from django_event_bus.registry import get_receivers, register


def test_register_and_get_receivers():
    def handler(**kwargs):
        pass

    register("some.unique_event", handler)

    assert handler in get_receivers("some.unique_event")


def test_get_receivers_returns_empty_list_for_unknown_event():
    assert get_receivers("nothing.registered.here") == []
