"""A named home for a project's spec set.

Declare each operation once; every transport reads the same source instead of
enumerating the specs again. Behavioural (a registry holds state), so it lives
here rather than in ``types/`` — where its value type, ``RegisteredSpec``,
does.
"""

from django_spec_rest.registry.capability_manifest import capability_manifest
from django_spec_rest.registry.spec_registry import SpecRegistry

__all__ = ["SpecRegistry", "capability_manifest"]
