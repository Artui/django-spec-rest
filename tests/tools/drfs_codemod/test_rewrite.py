"""``rewrite_source``: what one module's drfs declarations become, and what is left marked.

Each source is a drfs module as a project holds it; the output is compared as
text where the spelling is the claim (an import's module, a keyword's seat),
and executed where the claim is the object a kernel spec is built with.
"""

from __future__ import annotations

import textwrap
import types
from pathlib import Path

import pytest
from drfs_codemod.rewrite import MARKER, rewrite_source

from tests.testapp.serializers import AuthorSerializer


def _rewrite(source: str, roots: tuple[Path, ...] = ()) -> tuple[str, list[str]]:
    output, findings = rewrite_source(textwrap.dedent(source), Path("app/specs.py"), roots)
    return output, [finding.reason for finding in findings]


def _module(output: str) -> types.ModuleType:
    module = types.ModuleType("rewritten")
    exec(compile(output, "rewritten.py", "exec"), module.__dict__)
    return module


def _markers(output: str) -> list[str]:
    prefix = f"# {MARKER} "
    return [line.strip()[len(prefix) :] for line in output.splitlines() if prefix in line]


class TestImportsByModulePath:
    """One spelling, two objects: which ``NotPermitted`` a name is depends on where it came from."""

    def test_the_drfs_twin_and_the_kernel_s_class_from_one_drfs_module(self) -> None:
        output, findings = _rewrite(
            """\
            from rest_framework_services.service_specs.not_permitted import KernelNotPermitted, NotPermitted


            def refuse(kernel: bool) -> None:
                raise KernelNotPermitted() if kernel else NotPermitted()
            """
        )
        assert "from django_service_specs import NotPermitted\n" in output
        assert (
            "from django_spec_rest.service_specs.drf_not_permitted import DRFNotPermitted\n"
            in output
        )
        assert "rest_framework_services" not in output
        assert "raise NotPermitted() if kernel else DRFNotPermitted()" in output
        assert findings == []

    def test_the_kernel_s_namesake_is_left_as_the_kernel_s(self) -> None:
        """The same spelling imported from the kernel is the kernel's class, and stays it."""
        source = """\
            from django_service_specs import NotPermitted
            from rest_framework_services import ServiceSpec


            def refuse() -> None:
                raise NotPermitted()
            """
        output, _ = _rewrite(source)
        assert "raise NotPermitted()" in output
        assert "DRFNotPermitted" not in output
        assert "from django_service_specs import ServiceSpec, NotPermitted\n" in output

    def test_a_dotted_string_is_rewritten_by_its_module(self) -> None:
        output, _ = _rewrite(
            """\
            EXCEPTION = "rest_framework_services.service_specs.not_permitted.NotPermitted"
            KERNEL = "rest_framework_services.service_specs.not_permitted.KernelNotPermitted"
            """
        )
        assert (
            'EXCEPTION = "django_spec_rest.service_specs.drf_not_permitted.DRFNotPermitted"'
            in output
        )
        assert 'KERNEL = "django_service_specs.NotPermitted"' in output

    def test_an_alias_is_kept_where_it_differs_from_the_target(self) -> None:
        output, _ = _rewrite(
            """\
            from rest_framework_services.service_specs.not_permitted import NotPermitted as Refused

            ERROR = Refused
            """
        )
        assert (
            "from django_spec_rest.service_specs.drf_not_permitted import DRFNotPermitted as Refused"
            in output
        )
        assert "ERROR = Refused" in output

    def test_a_name_with_nowhere_to_go_is_marked_where_it_is_used(self) -> None:
        output, findings = _rewrite(
            """\
            from rest_framework_services import OfflineContract, ServiceSpec

            CONTRACT = OfflineContract
            """
        )
        reason = (
            "OfflineContract: declare its parts on their seats: field_audiences on "
            "SerializerPresenter, url_kwargs as a Parameter in the selector's reads= (a capture "
            "the model must never see is a server argument), query_params as shapes= on the "
            "spec; see 'Declaring a spec' on the moving page"
        )
        assert findings == [reason, reason]
        assert "from rest_framework_services import OfflineContract\n" in output
        assert "from django_service_specs import ServiceSpec\n" in output

    def test_a_polymorphic_spec_is_marked_with_its_counterpart(self) -> None:
        output, findings = _rewrite(
            """\
            from rest_framework_services import PolymorphicServiceSpec

            LOGIN = PolymorphicServiceSpec
            """
        )
        reason = (
            "PolymorphicServiceSpec: declare a DiscriminatedAction to keep one URL, else one "
            "kernel spec per route or action; permission_strategy= is dropped"
        )
        assert findings == [reason, reason]
        assert "from rest_framework_services import PolymorphicServiceSpec\n" in output

    def test_a_name_with_nowhere_to_go_and_no_use_is_dropped_unmarked(self) -> None:
        output, findings = _rewrite("from rest_framework_services import OfflineContract\n")
        assert output.strip() == ""
        assert findings == []

    def test_a_module_import_of_drfs_is_marked_and_its_specs_left_whole(self) -> None:
        source = textwrap.dedent(
            """\
            import rest_framework_services as drfs

            spec = drfs.ServiceSpec(service=print, input_serializer=In)
            """
        )
        output, findings = _rewrite(source)
        assert findings == [
            "import rest_framework_services: import each name it is used for from its new module"
        ]
        assert output.endswith(source)


class TestIdempotent:
    """A second run over the output changes nothing, and reports the same sites."""

    SOURCE = """\
        from rest_framework_services import SelectorKind, SelectorSpec, ServiceSpec, UrlKwarg

        from app import selectors


        def by_pk(*, pk: int):
            return pk


        target = SelectorSpec(kind=SelectorKind.RETRIEVE, selector=by_pk)

        listing = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=selectors.everything,
            reads=[UrlKwarg(name="board")],
        )

        create = ServiceSpec(service=print, success_status=201, permission_classes=[])
        """

    def test_a_second_run_changes_nothing(self) -> None:
        first, first_findings = _rewrite(self.SOURCE)
        second, second_findings = _rewrite(first)
        assert second == first
        assert second_findings == first_findings
        assert len(_markers(first)) == len(set(_markers(first))) == len(first_findings)

    def test_a_file_already_carrying_markers_gains_none(self) -> None:
        """The marker a run writes above a selector it cannot finish is not written twice."""
        first, _ = _rewrite(self.SOURCE)
        assert _markers(first)[0].startswith("selector=by_pk takes by name")
        second, _ = _rewrite(first)
        assert _markers(second) == _markers(first)

    def test_a_kernel_module_is_left_alone(self) -> None:
        source = textwrap.dedent(
            """\
            from django_service_specs import Parameter, Parameters, SelectorKind, SelectorSpec

            spec = SelectorSpec(
                kind=SelectorKind.RETRIEVE,
                selector=lambda *, pk: pk,
                reads=Parameters.of(Parameter("pk", "integer", required=True)),
            )
            """
        )
        assert _rewrite(source) == (source, [])


class TestSeats:
    """The serializers, contexts and permissions move onto the kernel's seats."""

    def test_the_serializers_and_their_contexts(self) -> None:
        output, findings = _rewrite(
            """\
            from rest_framework_services import ServiceSpec


            def context(*, request):
                return {}


            spec = ServiceSpec(
                service=print,
                input_serializer=In,
                input_serializer_context=context,
                output_serializer=Out,
                output_serializer_context=context,
            )
            """
        )
        assert "validator=SerializerValidator(In, serializer_context=context)," in output
        assert "presenter=SerializerPresenter(Out, serializer_context=context)," in output
        assert "_serializer" not in output.replace("SerializerValidator", "").replace(
            "SerializerPresenter", ""
        ).replace("serializer_context", "")
        assert findings == []

    def test_a_context_with_no_seat_is_marked(self) -> None:
        _, findings = _rewrite(
            """\
            from rest_framework_services import ServiceSpec

            spec = ServiceSpec(service=print, input_serializer_context=context)
            """
        )
        assert findings == [
            "input_serializer_context with no input_serializer has no seat to carry it: "
            "was input_serializer_context=context"
        ]

    def test_permission_classes_become_one_drf_permission_check(self) -> None:
        output, findings = _rewrite(
            """\
            from rest_framework.permissions import IsAdminUser, IsAuthenticated
            from rest_framework_services import ServiceSpec

            spec = ServiceSpec(service=print, permission_classes=[IsAuthenticated, IsAdminUser])
            """
        )
        assert "permissions=(DRFPermissionCheck([IsAuthenticated, IsAdminUser]),)" in output
        assert (
            "from django_spec_rest.service_specs.drf_permission_check import DRFPermissionCheck"
            in output
        )
        assert findings == []

    def test_an_empty_permission_classes_is_left_for_a_decision(self) -> None:
        output, findings = _rewrite(
            """\
            from rest_framework_services import ServiceSpec

            spec = ServiceSpec(service=print, permission_classes=[])
            """
        )
        assert "permission" not in output.split(f"# {MARKER}")[-1].split("\n", 1)[1]
        assert findings == [
            "an empty permission_classes: say permissions=(Unrestricted(),) if the spec "
            "admits everyone: was permission_classes=[]"
        ]

    def test_permissions_on_a_nested_selector_are_refused(self) -> None:
        output, findings = _rewrite(
            """\
            from rest_framework_services import SelectorKind, SelectorSpec, ServiceSpec

            spec = ServiceSpec(
                service=print,
                instance_selector_spec=SelectorSpec(
                    kind=SelectorKind.RETRIEVE, selector=lambda: None, permission_classes=[IsOwner]
                ),
            )
            """
        )
        assert "IsOwner" not in output.split(f"# {MARKER}")[-1].split("\n", 1)[1]
        assert findings == [
            "the kernel refuses permissions on a nested selector: declare them on the spec "
            "served: was permission_classes=[IsOwner]"
        ]

    def test_a_shared_schema_registry_goes_on_both_seats(self) -> None:
        output, findings = _rewrite(
            """\
            from rest_framework_services import ServiceSpec

            spec = ServiceSpec(
                service=print, input_serializer=In, output_serializer=Out, json_schema_registry=SHARED
            )
            """
        )
        assert "SerializerValidator(In, json_schema_registry=SHARED)" in output
        assert "SerializerPresenter(Out, json_schema_registry=SHARED)" in output
        assert findings == []


class TestTheOutputSelectorHoist:
    """drfs said a service's output on its output selector; the kernel's is the service's presenter."""

    def test_a_serializer_only_selector_becomes_the_presenter(self) -> None:
        output, findings = _rewrite(
            """\
            from rest_framework_services import SelectorKind, SelectorSpec, ServiceSpec

            from tests.testapp.serializers import AuthorSerializer


            def context(*, result):
                return {"seen": result}


            spec = ServiceSpec(
                service=print,
                output_selector_spec=SelectorSpec(
                    kind=SelectorKind.RETRIEVE,
                    output_serializer=AuthorSerializer,
                    output_serializer_context=context,
                ),
            )
            """
        )
        assert "output_selector_spec" not in output
        assert findings == []
        spec = _module(output).spec
        assert spec.output_selector_spec is None
        assert spec.presenter.serializer_class is AuthorSerializer
        # drfs handed a service's output context the service's return as ``result``.
        assert spec.presenter.value_keyword == "result"
        assert spec.presenter.serializer_context(result=1) == {"seen": 1}

    def test_a_selector_that_re_reads_is_kept_beside_the_presenter(self) -> None:
        output, _ = _rewrite(
            """\
            from rest_framework_services import SelectorKind, SelectorSpec, ServiceSpec

            from tests.testapp.serializers import AuthorSerializer


            def reread(*, result):
                return result


            spec = ServiceSpec(
                service=print,
                output_selector_spec=SelectorSpec(
                    kind=SelectorKind.RETRIEVE, selector=reread, output_serializer=AuthorSerializer
                ),
            )
            """
        )
        spec = _module(output).spec
        assert spec.output_selector_spec.selector.__name__ == "reread"
        assert spec.presenter.serializer_class is AuthorSerializer

    def test_a_many_service_s_context_is_handed_no_value_keyword(self) -> None:
        output, _ = _rewrite(
            """\
            from rest_framework_services import ServiceSpec

            spec = ServiceSpec(service=print, many=True, output_serializer=Out, output_serializer_context=ctx)
            """
        )
        assert "SerializerPresenter(Out, serializer_context=ctx, value_keyword=None)" in output

    def test_an_output_selector_declared_elsewhere_is_marked(self) -> None:
        _, findings = _rewrite(
            """\
            from rest_framework_services import ServiceSpec

            spec = ServiceSpec(service=print, output_selector_spec=SHARED_OUTPUT)
            """
        )
        assert findings == [
            "its output_selector_spec is declared elsewhere: move that selector's output "
            "serializer onto this spec as presenter=SerializerPresenter(...)"
        ]


class TestDocumentServiceError:
    """drfs' flag is the kernel's metadata entry."""

    def test_true_with_no_metadata_becomes_the_entry(self) -> None:
        output, findings = _rewrite(
            """\
            from rest_framework_services import ServiceSpec

            spec = ServiceSpec(service=print, document_service_error=True)
            """
        )
        assert _module(output).spec.metadata == {"document_service_error": True}
        assert findings == []

    def test_true_beside_metadata_joins_it(self) -> None:
        output, findings = _rewrite(
            """\
            from rest_framework_services import ServiceSpec

            spec = ServiceSpec(service=print, metadata={"tag": "x"}, document_service_error=True)
            """
        )
        assert _module(output).spec.metadata == {"tag": "x", "document_service_error": True}
        assert findings == []

    @pytest.mark.parametrize("value", ["False", "None"])
    def test_false_or_none_is_dropped(self, value: str) -> None:
        output, findings = _rewrite(
            f"""\
            from rest_framework_services import ServiceSpec

            spec = ServiceSpec(service=print, document_service_error={value})
            """
        )
        assert "document_service_error" not in output
        assert _module(output).spec.metadata is None
        assert findings == []

    def test_a_computed_flag_is_marked(self) -> None:
        _, findings = _rewrite(
            """\
            from rest_framework_services import ServiceSpec

            spec = ServiceSpec(service=print, document_service_error=DOCUMENTED)
            """
        )
        assert findings == [
            'say {"document_service_error": True} in metadata where it is true: '
            "was document_service_error=DOCUMENTED"
        ]

    def test_true_beside_metadata_declared_elsewhere_is_marked(self) -> None:
        _, findings = _rewrite(
            """\
            from rest_framework_services import ServiceSpec

            spec = ServiceSpec(service=print, metadata=SHARED, document_service_error=True)
            """
        )
        assert findings == [
            'add "document_service_error": True to its metadata: was document_service_error=True'
        ]


class TestFieldAudiences:
    def test_they_go_on_the_presenter(self) -> None:
        output, findings = _rewrite(
            """\
            from rest_framework_services import FieldMarking, SelectorKind, SelectorSpec

            from tests.testapp.serializers import AuthorSerializer

            spec = SelectorSpec(
                kind=SelectorKind.LIST,
                selector=lambda: [],
                output_serializer=AuthorSerializer,
                field_audiences={"name": FieldMarking.hidden()},
            )
            """
        )
        assert findings == []
        presenter = _module(output).spec.presenter
        assert set(presenter.field_audiences) == {"name"}

    def test_with_no_presenter_they_are_marked(self) -> None:
        _, findings = _rewrite(
            """\
            from rest_framework_services import ServiceSpec

            spec = ServiceSpec(service=print, field_audiences=AUDIENCES)
            """
        )
        assert findings == [
            "field_audiences goes on a SerializerPresenter, and this spec has none: "
            "was field_audiences=AUDIENCES"
        ]

    def test_on_an_output_selector_they_are_marked(self) -> None:
        _, findings = _rewrite(
            """\
            from rest_framework_services import SelectorKind, SelectorSpec, ServiceSpec

            spec = ServiceSpec(
                service=print,
                output_selector_spec=SelectorSpec(
                    kind=SelectorKind.RETRIEVE, selector=reread, field_audiences=AUDIENCES
                ),
            )
            """
        )
        assert (
            "field_audiences on an output selector goes on the service's SerializerPresenter: "
            in (findings[0])
        )


class TestReads:
    """What a selector's signature named, drfs filled; the marker spells the ``reads=`` it needs."""

    @pytest.fixture
    def root(self, tmp_path: Path) -> Path:
        package = tmp_path / "shop"
        package.mkdir()
        (package / "__init__.py").write_text("")
        (package / "selectors.py").write_text(
            textwrap.dedent(
                """\
                def by_pk(*, pk: int, user):
                    return pk


                def search(*, q: str | None = None, ids: list[int], limit=10, flag: bool = False):
                    return []


                def anything(**kwargs):
                    return kwargs
                """
            )
        )
        return tmp_path

    def _reads(self, root: Path, imports: str, selector: str) -> list[str]:
        _, findings = _rewrite(
            f"""\
            from rest_framework_services import SelectorKind, SelectorSpec
            {imports}

            spec = SelectorSpec(kind=SelectorKind.LIST, selector={selector})
            """,
            (root,),
        )
        return findings

    def test_a_module_attribute_is_read_from_its_file(self, root: Path) -> None:
        """``user`` is a seed the kernel fills, so it is no read."""
        assert self._reads(root, "from shop import selectors", "selectors.by_pk") == [
            "selector=selectors.by_pk takes by name what drfs filled from the route or query "
            'string; where the caller sends it, declare reads=Parameters.of(Parameter("pk", '
            '"integer", required=True))'
        ]

    def test_an_imported_function_and_each_parameter_s_shape(self, root: Path) -> None:
        assert self._reads(root, "from shop.selectors import search", "search") == [
            "selector=search takes by name what drfs filled from the route or query string; "
            'where the caller sends it, declare reads=Parameters.of(Parameter("q", "string"), '
            'Parameter("ids", "array", items="integer", required=True), Parameter("limit", '
            '"string", default=10), Parameter("flag", "boolean", default=False)) '
            "(type guessed for limit)"
        ]

    def test_a_dotted_import_of_the_module(self, root: Path) -> None:
        assert self._reads(root, "import shop.selectors", "shop.selectors.by_pk")[0].startswith(
            "selector=shop.selectors.by_pk takes by name"
        )

    def test_a_selector_taking_any_keyword(self, root: Path) -> None:
        assert self._reads(root, "from shop import selectors", "selectors.anything") == [
            "selector=selectors.anything: its selector takes **kwargs: declare in reads= each "
            "key it reads"
        ]

    def test_a_lambda_is_read_where_it_stands(self, root: Path) -> None:
        assert self._reads(root, "", "lambda *, board_id: []") == [
            "selector=lambda *, board_id: [] takes by name what drfs filled from the route or "
            "query string; where the caller sends it, declare reads=Parameters.of(Parameter("
            '"board_id", "string", required=True)) (type guessed for board_id)'
        ]

    def test_a_selector_naming_only_seeds_needs_no_reads(self, root: Path) -> None:
        assert self._reads(root, "", "lambda *, user, request: []") == []

    @pytest.mark.parametrize(
        "imports, selector",
        [
            ("from shop import missing", "missing.by_pk"),
            ("from shop import selectors", "selectors.not_there"),
            ("", "unknown.thing"),
        ],
    )
    def test_a_selector_out_of_reach(self, root: Path, imports: str, selector: str) -> None:
        assert self._reads(root, imports, selector) == [
            f"its selector {selector} is out of reach: declare in reads= what drfs read by its "
            "signature"
        ]

    def test_a_selector_that_is_no_name(self, root: Path) -> None:
        assert self._reads(root, "", "factory()") == [
            "its selector is no name: declare in reads= what drfs read by its signature"
        ]

    def test_a_drfs_reads_list_is_left_for_the_kernel_s_parameters(self, root: Path) -> None:
        output, findings = _rewrite(
            """\
            from rest_framework_services import QueryParam, SelectorKind, SelectorSpec

            spec = SelectorSpec(kind=SelectorKind.LIST, selector=lambda: [], reads=[QueryParam(name="q")])
            """,
            (root,),
        )
        # The list leaves the call for the marker, so its import goes with it.
        assert findings == [
            "declare each read as a kernel Parameter: reads=Parameters.of(Parameter(...)): "
            'was reads=[QueryParam(name="q")]'
        ]
        assert "QueryParam" not in output.split(f"# {MARKER}")[0]


def test_an_answer_with_no_view_here_is_marked() -> None:
    _, findings = _rewrite(
        """\
        from rest_framework_services import ServiceSpec

        spec = ServiceSpec(service=print, success_status=201)
        """
    )
    assert findings == [
        "success_status=201 is the view's or the action's: set success_status on the view, "
        "@service_action(..., success_status=...), or get_<action>_success_status on the viewset"
    ]


def test_a_shaped_validator_seat_is_executable() -> None:
    """The rewritten spec builds: its seats are the objects the kernel takes."""
    output, _ = _rewrite(
        """\
        from rest_framework_services import ServiceSpec

        from tests.testapp.serializers import AuthorSerializer

        spec = ServiceSpec(service=print, input_serializer=AuthorSerializer)
        """
    )
    assert _module(output).spec.validator.serializer is AuthorSerializer
