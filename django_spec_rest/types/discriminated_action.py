from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import NoReturn

from django_service_specs.specs.service_spec import ServiceSpec


@dataclass(frozen=True)
class DiscriminatedAction:
    """One write action, one URL, and the request choosing which kernel spec serves it."""

    discriminator: Callable[..., str]
    specs: Mapping[str, ServiceSpec]

    def as_kernel_spec(self) -> NoReturn:
        """Refuse to compile: the kernel asks this of anything handed to it as a spec."""
        raise TypeError(
            f"DiscriminatedAction is not a kernel spec, so it cannot be dispatched or registered "
            f"as one. Register each of its variants on its own: {sorted(self.specs)}."
        )
