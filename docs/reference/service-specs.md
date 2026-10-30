# DRF seats

A kernel spec has three seats DRF can fill: its `validator`, its `presenter`
and its `permissions`. This page is the adapters that fill them, the DRF
refusal classes the kernel's refusals become, and the helpers a caller off
HTTP uses to give a serializer the context it reads.

None of these is exported from the package root; import each from its leaf
module:

```python
from django_spec_rest.service_specs.drf_permission_check import DRFPermissionCheck
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
```

## The seats

::: django_spec_rest.service_specs.serializer_validator.SerializerValidator

::: django_spec_rest.service_specs.serializer_presenter.SerializerPresenter

::: django_spec_rest.service_specs.drf_permission_check.DRFPermissionCheck

## Refusals that are DRF's as well

Each class is the kernel's refusal and DRF's exception at once, so a caller of
the kernel's `dispatch` catches it by the kernel's class and DRF's exception
handler answers it with DRF's status.

::: django_spec_rest.service_specs.drf_invalid_arguments.DRFInvalidArguments

::: django_spec_rest.service_specs.drf_not_permitted.DRFNotPermitted

::: django_spec_rest.service_specs.drf_not_authenticated.DRFNotAuthenticated

::: django_spec_rest.service_specs.drf_principal_unavailable.DRFPrincipalUnavailable

::: django_spec_rest.service_specs.drf_service_validation_error.DRFServiceValidationError

## Translating refusals

::: django_spec_rest.service_specs.translate_dispatch_errors.translate_dispatch_errors

::: django_spec_rest.service_specs.translate_drf_refusals.translate_drf_refusals

::: django_spec_rest.service_specs.translating_drf_refusals.translating_drf_refusals

::: django_spec_rest.service_specs.register_drf_row_errors.register_drf_row_errors

## Serializer context

::: django_spec_rest.service_specs.base_serializer_context.base_serializer_context

::: django_spec_rest.service_specs.build_offline_context.build_offline_context

::: django_spec_rest.service_specs.renderable_serializer_class.renderable_serializer_class
