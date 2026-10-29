"""Transport-neutral spec dispatch.

The single execution path an alternate transport (the MCP server, a CLI, a
task runner) drives instead of re-implementing validate → resolve → run →
shape → materialize. The HTTP view layer keeps its own request-coupled
orchestration; everything off the HTTP path composes these.
"""

from django_spec_rest.dispatch.adispatch_spec import adispatch_spec
from django_spec_rest.dispatch.aenforce_affordances import aenforce_affordances
from django_spec_rest.dispatch.arender_for_audience import arender_for_audience
from django_spec_rest.dispatch.arender_spec_output import arender_spec_output
from django_spec_rest.dispatch.aunmet_operation_affordance import (
    aunmet_operation_affordance,
)
from django_spec_rest.dispatch.base_pool import base_pool
from django_spec_rest.dispatch.base_serializer_context import base_serializer_context
from django_spec_rest.dispatch.build_offline_context import build_offline_context
from django_spec_rest.dispatch.combine_progress import combine_progress
from django_spec_rest.dispatch.dispatch_spec import dispatch_spec
from django_spec_rest.dispatch.enforce_affordances import enforce_affordances
from django_spec_rest.dispatch.enforce_permissions import enforce_permissions

# Must stay *after* ``base_pool``. Importing that module imports this one as
# a side effect, and Python then binds the **submodule** onto the package —
# overwriting a from-import placed earlier, so ``null_progress`` would resolve
# to a module object rather than the function. Alphabetical order happens to be
# correct here; if these are ever reordered, keep this one last of the two.
from django_spec_rest.dispatch.null_progress import null_progress
from django_spec_rest.dispatch.operation_affordances import operation_affordances
from django_spec_rest.dispatch.paginate_output import (
    DEFAULT_PAGE_SIZE,
    paginate_output,
)
from django_spec_rest.dispatch.provider_keys import provider_keys
from django_spec_rest.dispatch.render_for_audience import render_for_audience
from django_spec_rest.dispatch.render_spec_output import render_spec_output
from django_spec_rest.dispatch.renderable_serializer_class import (
    renderable_serializer_class,
)
from django_spec_rest.dispatch.unguarded_specs import unguarded_specs
from django_spec_rest.dispatch.unmet_operation_affordance import (
    unmet_operation_affordance,
)

# Public from the shared ``utils`` rather than a module of its own, because the
# declared-input and fillable reads beside it there are built on it.
from django_spec_rest.dispatch.utils import server_owned_keys

__all__ = [
    "adispatch_spec",
    "aenforce_affordances",
    "arender_for_audience",
    "arender_spec_output",
    "aunmet_operation_affordance",
    "base_pool",
    "base_serializer_context",
    "build_offline_context",
    "combine_progress",
    "dispatch_spec",
    "enforce_affordances",
    "enforce_permissions",
    "DEFAULT_PAGE_SIZE",
    "null_progress",
    "operation_affordances",
    "paginate_output",
    "provider_keys",
    "render_for_audience",
    "render_spec_output",
    "renderable_serializer_class",
    "server_owned_keys",
    "unguarded_specs",
    "unmet_operation_affordance",
]
