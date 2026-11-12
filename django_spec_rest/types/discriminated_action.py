from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import NoReturn

from django_service_specs.specs.service_spec import ServiceSpec


@dataclass(frozen=True)
class DiscriminatedAction:
    """One write action, one URL, and the request choosing which kernel spec serves it.

    One spec per route stays the default; this is the opt-in for an endpoint
    that must keep one URL. It attaches as an ``action_specs`` entry under
    ``create``, ``update``, ``partial_update`` or ``destroy``, or as
    ``@service_action(action)``, and ``as_view()`` refuses it anywhere else.
    It is this transport's alone and never a kernel spec: agents and MCP
    register each variant on its own, so ``as_kernel_spec()`` raises.

    ``discriminator`` picks the key: a sync callable declaring any of
    ``request``, ``data`` (the raw ``request.data``), ``user``, ``view`` and
    ``call_context``, or ``**kwargs``, which is handed all but the last.
    ``specs`` maps each key it may answer to the kernel ``ServiceSpec`` serving
    it, and each is asked what a plain entry of that action is asked.

    A caller every variant refuses is refused before the body is read and
    before the discriminator runs. Otherwise the discriminator chooses and the
    chosen variant runs as a plain entry would, its own checks deciding. A
    callable ``success_status`` or ``response_finalizer`` on such an action may
    declare ``variant``, the chosen key.

    These are checked by ``as_view()`` or the decorator, which know the action
    and the view, rather than here.
    """

    discriminator: Callable[..., str]
    specs: Mapping[str, ServiceSpec]

    def as_kernel_spec(self) -> NoReturn:
        """Refuse to compile: the kernel asks this of anything handed to it as a spec."""
        raise TypeError(
            f"DiscriminatedAction is not a kernel spec, so it cannot be dispatched or registered "
            f"as one. Register each of its variants on its own: {sorted(self.specs)}."
        )
