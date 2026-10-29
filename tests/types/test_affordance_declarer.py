"""``AffordanceDeclarer``: the spec a ``SelectorSpec``'s ``affordances`` maps a name to."""

from __future__ import annotations

from dataclasses import fields

from django.db.models import Q

from django_spec_rest.types.affordance import Affordance
from django_spec_rest.types.affordance_declarer import AffordanceDeclarer
from django_spec_rest.types.selector_kind import SelectorKind
from django_spec_rest.types.selector_spec import SelectorSpec
from django_spec_rest.types.service_spec import ServiceSpec

ARCHIVED = Affordance(code="archived", reason="Archived.", when=Q(archived=False))


def _noop() -> None:
    return None


def test_a_service_spec_is_one() -> None:
    declared = [ARCHIVED]
    spec = ServiceSpec(service=_noop, affordances=declared)
    assert isinstance(spec, AffordanceDeclarer)
    assert spec.affordances is declared


def test_a_selector_spec_is_not_one_though_it_has_affordances_of_its_own() -> None:
    # The reason the base is nominal: a check by attribute would pass this.
    selector = SelectorSpec(
        kind=SelectorKind.LIST, selector=list, affordances={"rename": ServiceSpec(service=_noop)}
    )
    assert hasattr(selector, "affordances")
    assert not isinstance(selector, AffordanceDeclarer)


def test_it_adds_no_field_to_a_service_spec() -> None:
    # A read-only property and no value: the base declares what is read, and
    # ``ServiceSpec`` keeps its own ``affordances`` field and default, which
    # shadows the property on the class and on every instance.
    assert isinstance(vars(AffordanceDeclarer)["affordances"], property)
    (field,) = (field for field in fields(ServiceSpec) if field.name == "affordances")
    assert field.default is None
    assert vars(ServiceSpec)["affordances"] is None
    assert ServiceSpec(service=_noop).affordances is None
