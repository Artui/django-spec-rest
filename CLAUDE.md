# CLAUDE.md

Conventions for writing code in this repo. For *what* the library does, see [`README.md`](README.md).

- Package on PyPI: `django-spec-rest`
- Importable name: `django_spec_rest`
- Build backend: hatchling
- Serves [`django-service-specs`](https://github.com/Artui/django-service-specs) (the kernel) specs over DRF: views and viewsets take the kernel's `ServiceSpec` / `SelectorSpec`, the kernel's `dispatch` runs every call, and DRF fills three of a spec's seats (`SerializerValidator`, `SerializerPresenter`, `DRFPermissionCheck`). The root `__all__` exports only the names this package owns and nothing of the kernel's (`tests/test_dispatch_surface.py` pins the set exactly, and refuses a kernel name creeping back), so a spec's own behaviour (its fields, its typed check, its refusals) belongs to the kernel and is changed there, not here.

---

## Commands

Use the Makefile targets for everything; CI and pre-commit both call them.

```bash
make init           # uv sync --all-groups + pre-commit install (first-checkout setup)
make test           # uv run pytest (with --cov=django_spec_rest --cov-fail-under=100)
make examples       # the example project's suite: cd examples && uv run python manage.py test invoices
make lint           # ruff check + ty check django_spec_rest
make lint-fix       # ruff check --fix
make format         # ruff format
make format-check   # ruff format --check --diff
make type-check     # ty check django_spec_rest
make docs-serve     # live-reload docs at http://localhost:8000 (needs mkdocs.yml)
make docs-build     # mkdocs build --strict (fails on broken links)
```

`make help` lists every target with a one-line description.

---

## Structural rules

These are non-negotiable. They are what keep the package navigable.

1. **One exported class or function per file.** The file is named after the exported symbol in `snake_case`. `MyClass` lives in `my_class.py`; `do_thing` lives in `do_thing.py`.
2. **Private helpers used only in one file** stay in that file with a `_name` prefix.
3. **Non-exported helpers shared across files in a package** go in that package's `utils.py`. Classes are allowed in `utils.py` if they're internal infrastructure (e.g. `MutationFlowMixin` lived there before being promoted to its own file when it became public).
4. **Top-level imports only.** Lazy / function-local imports are forbidden unless a circular import is diagnosed and proven, *or* the import targets a proven optional dependency (declared in `[project.optional-dependencies]` and gated behind an explicit `enable_*()` opt-in helper). In either case document the reason inline. Canonical optional-dep example: `django_spec_rest/openapi/enable_openapi.py`.
5. **Full type annotations on every function and method signature.** `Any` is allowed at integration boundaries (DRF serializers, Django ORM); avoid it inside the package.
6. **Re-exports go in `__init__.py`.** Each package's `__init__.py` lists its public surface in `__all__`. The top-level `django_spec_rest/__init__.py` re-exports the user-facing API. Two packages carry no `__all__`: `service_specs/`, whose names are imported from their leaf modules (`django_spec_rest.service_specs.serializer_validator.SerializerValidator`), and `dispatch/`, which has no public name at all.
7. **`service_specs/` is the adapter over the kernel.** It supplies the kernel's seats from DRF (`SerializerValidator`, `SerializerPresenter`, `DRFPermissionCheck`), derives the variant of a spec one request dispatches (`kernel_spec_variant`: partial for a `PATCH`, lenient for a form body), and translates the kernel's refusals into DRF's and back (`translate_dispatch_errors`, `translate_drf_refusals`, the `DRF*` twins such as `DRFInvalidArguments` and `DRFNotPermitted`, `register_drf_row_errors`). It imports DRF by design and must never import the HTTP views or `dispatch/`: `dispatch/` calls the adapter, never the reverse. Outside the transport packages (`views/`, `viewsets/`, `openapi/`), which import it freely, only `dispatch/kernel_edge.py` and `dispatch/kernel_refusals.py` do. All three directions are held by tests (see *Imports inside the package*).

---

## Public API naming

A spec's fields are the kernel's, and so is the rule that names them; a new spec field is a change to `django-service-specs`. What this package names:

1. **Views and viewsets mirror DRF's generic views**, with `Service` for a write and `Selector` for a read: `ServiceCreateView`, `SelectorListView`, `ServiceViewSet`, `ServiceCreateMixin`.
2. **A DRF seat is named for the DRF object it wraps and the kernel seat it fills**: `SerializerValidator`, `SerializerPresenter`, `DRFPermissionCheck`.
3. **A refusal that is DRF's as well as the kernel's is prefixed `DRF` and subclasses both**: `DRFNotPermitted` is the kernel's `NotPermitted` and DRF's `PermissionDenied`, and `DRFNotAuthenticated` the kernel's `NotPermitted` answered as DRF's `NotAuthenticated` (a 401 where an authenticator supplies a challenge, a 403 where none does, as DRF answers it). The kernel's name always means the kernel's class.

---

## Adding a new feature

**Always work on a dedicated branch.** Any new feature, bugfix, or version-bump
work happens on a freshly-cut branch — never on `main` directly. Push to that
branch and open a PR. `main` only ever advances through merges of reviewed
PRs (or, for releases, the `Release X.Y.Z` commit pushed by
`make release-publish` once the release branch has been merged).

```bash
git switch -c feature/short-name   # before you start
# ... edits, commits ...
git push -u origin feature/short-name
gh pr create
```

A typical change touches three places:

1. The source file (one new `.py` per new class/function).
2. The package's `__init__.py` (add to imports + `__all__`).
3. A test file under `tests/` mirroring the source path (`django_spec_rest/foo/bar.py` → `tests/foo/test_bar.py`).

Then verify:

```bash
make lint-fix
make format
make test
```

`make test` enforces 100% line + branch coverage. New branches must be exercised, not annotated away.

If the new symbol is part of the public API, also add it to the top-level `django_spec_rest/__init__.py` and to `CHANGELOG.md` under `[Unreleased]`.

---

## Tests

- Live in `tests/`, mirroring the source tree. `tests/service_specs/test_serializer_validator.py` tests `django_spec_rest/service_specs/serializer_validator.py`.
- Each test file is named `test_<module_name>.py`.
- Async tests rely on `pytest-asyncio` (`asyncio_mode = "auto"` in `pyproject.toml`); just write `async def test_...`.
- DB-touching tests use `@pytest.mark.django_db`; async DB tests use `@pytest.mark.django_db(transaction=True)`.
- The minimal Django app for integration tests lives at `tests/testapp/`. Add models there only if a new test needs them; prefer reusing the existing ones.
- 100% coverage is enforced via `--cov-fail-under=100`. Branch coverage too. If a branch is genuinely unreachable, restructure rather than `# pragma: no cover`-ing.

---

## Type checking

`ty` is scoped to `django_spec_rest/` only — Django's dynamic descriptors (`Model.objects` in particular) trip the checker when it walks `tests/`. If `ty` complains about a piece of source code, fix the source rather than scoping the checker more narrowly.

Dev deps include `django-stubs` and `djangorestframework-stubs`, so DRF and Django types are known to `ty`.

Common patches you'll still need inside the package:

- In **standalone mixins** (classes that don't inherit from `GenericAPIView` directly), attributes like `self.request`, `self.kwargs`, `self.action`, `self.get_object` aren't in scope at definition time. Declare them at the top of the class as `attr: Any` (or a more specific type) with a comment naming the parent.
- `super()` calls in standalone mixins to methods that only arrive at concrete composition time (e.g. `get_queryset`, `get_object`, `get_serializer_class`) still require `# ty: ignore[unresolved-attribute]`. In concrete view classes that extend `GenericAPIView` directly, those calls are fully resolved by the stubs.
- `get_serializer_class()` overrides must return `type[BaseSerializer[Any]]` — that is what DRF's stubs declare as the return type of the base method.

`ty` runs on every commit via the pre-commit hook and in CI.

---

## Linting and formatting

- `ruff check` enforces `E`, `F`, `UP`, `B`, `SIM`, `I`, `TID` (see `[tool.ruff.lint]` in `pyproject.toml`).
- `ruff format` is the source of truth for layout. Don't fight it.
- The pre-commit hook runs `make lint-fix` (auto-applies safe fixes) and `make format` (rewrites). Commits should be clean before push; CI will reject otherwise.
- **Use `...` (Ellipsis) instead of `pass` for empty function and class bodies.** Includes Protocol stubs, test fixtures, no-op viewset action methods stubbed out for `@service_action`, and bare placeholder classes. `pass` is reserved for intentionally-empty *statement* contexts (e.g. `try: ... except FooError: pass`) where Ellipsis would read as a literal expression rather than a no-op. This one stays prose: no ruff rule prefers `...` over `pass`, and a pygrep on a bare `pass` would fire on the allowed `try`/`except` form.

**Three of the rules above are now enforced, not remembered.** `ruff` carries the future-annotations import (`isort.required-imports`, with `__init__.py` and `migrations/` exempt) and the ban on every relative form including single-dot (`ban-relative-imports = "all"` — `TID` alone defaults to `parents`, so `from .foo import x` slipped through). A pygrep pre-commit hook carries the rest: no mypy-style `# type: ignore` inside the package. The ban on `if TYPE_CHECKING:` under *Imports inside the package* is enforced too, by `TID251`. Change the rule here and change the config with it, or they drift apart again.

  The mypy-pragma hook is scoped to `django_spec_rest/` on purpose, because that is exactly what `ty` checks. Under `tests/` and `examples/` no checker reads either pragma, while an editor running mypy or pyright does honour `# type: ignore` — rewriting those would turn something that still works into a no-op everywhere.

---

## Imports inside the package

- Always absolute, fully qualified: `from django_spec_rest.service_specs.serializer_validator import SerializerValidator`. **Never** relative imports — no `from . import x`, no `from .foo import Bar`, no `from ..pkg import baz`. This applies inside the package and inside `tests/` (use `from tests.testapp.models import …`).
- isort is wired through ruff (`I` rules). Order: stdlib → third-party → first-party. `django_spec_rest` and the test app are first-party.
- A package's `__init__.py` is the only file that re-exports; downstream files import from the leaf module, not from the package's `__init__`.
- **`types/` is the dependency sink.** Value-shape carriers (`ServiceView`, `ViewHooks`, `HttpExtras`, the offline request and context) live there. `views/`, `viewsets/`, `selectors/`, `dispatch/` and `service_specs/` may import *from* `types/`; `types/` imports nothing else from the package. If a `types/` member needs a shape living elsewhere, move that shape into `types/` first (this is why `ServiceView` lives in `types/` rather than `views/`).
- **Imports of DRF and of the HTTP views from outside the transport are ratcheted.** `tests/test_import_boundaries.py` lists every module outside `views/`, `viewsets/`, `openapi/` and the adapter `service_specs/` that imports `rest_framework` or `django_spec_rest.views`, and what it imports. An unlisted import fails, and so does a listed one that no longer exists, so both lists can only shrink. The adapter is walled separately (`EDGE_PACKAGES`): `ALLOWED_EDGE_DRF_IMPORTS` lists each of its modules' DRF imports with the reason beside it and ratchets both ways, `test_the_adapter_never_imports_the_http_views` refuses any import of `views/` or `viewsets/` from it, and `test_the_adapter_never_imports_dispatch` any import of `dispatch/`. Who imports the adapter is pinned exactly by `ALLOWED_ADAPTER_IMPORTERS`: `dispatch/kernel_edge.py` and `dispatch/kernel_refusals.py`, the kernel route. A new importer, or one that no longer imports it, fails `test_only_the_edge_imports_the_adapter`; the package root and the transport packages are outside that walk. A new entry in any of these lists is a decision to write down beside the entry, never a side effect. When you move something *out* of `views/`, delete its entries in the same change.
- **No `if TYPE_CHECKING:` guard in the package.** A guard hides an import cycle from the interpreter while the type checker still sees it, so every guard is a cycle waiting to be broken, and a function-local import is no substitute for breaking it (the older function-local imports that name a cycle stay until each is broken the same way). The ban is ruff's `TID251` (`[tool.ruff.lint.flake8-tidy-imports.banned-api]`, so `make lint` and CI run it). Break the cycle by structure: put the shared name in a leaf module of `types/`, type the parameter with a base class or `Any`, or reverse an edge. No file is exempt from the ban today; a `per-file-ignores` entry for one is a decision, not a side effect.
- **Don't eagerly import Django models** (`django.contrib.auth.models`, `django.db.models.<concrete>`, etc.) at package-import time. A project may import the package before the app registry is ready (at the top of an `AppConfig` module or an app's `__init__`, or before `django.setup()`), where an eager model import raises `AppRegistryNotReady`. `tests/test_import_before_setup.py` holds this: it imports every module of the package before `django.setup()`. If you need a precise type, prefer `Any` for that field (the framework treats `request.user` as an integration boundary; see `types/http_extras.py:UserT`), or move the import into a non-eagerly-loaded module.

---

## Compatibility floor

| Axis | Floor | Tested ceiling |
|---|---|---|
| Python | 3.10 | 3.14 |
| Django | 4.2 | 6.0 |
| DRF | 3.14 | latest |
| django-service-specs | 0.20.0 | latest |

Python 3.10 syntax / stdlib features are fair game (`match` statements, PEP 604 union syntax, etc.). Newer stdlib symbols (`Unpack`, `NotRequired`, `assert_type`, `TypeVar` with `default=...`, `override`) must be imported from `typing_extensions` so 3.10 / 3.11 keep working — `typing_extensions` re-exports them on every supported version. PEP 728's `TypedDict(..., extra_items=...)` is deliberately not used (no `typing_extensions` backport, blocks mypy). PEP 695 `class C[T]:` / `def f[T](...)` / `type X = …` syntax is also avoided — the package consistently uses `TypeVar(...)` + `Generic[T]`; don't "modernise" existing TypeVar uses on sight (the `UP040`, `UP046`, `UP047` ruff rules are ignored project-wide). CI runs the full Python × Django product, so any combo-specific bug surfaces fast.

`from __future__ import annotations` is at the top of every `.py` file in the package that has annotations (i.e. everything except bare re-export `__init__.py` files). Keep it that way.

---

## CI and pre-commit

`.github/workflows/tests.yml` runs on every push to `main` and every PR:

- `lint` job — `ruff check`, `ruff format --check --diff`, `ty check django_spec_rest`.
- `docs` job — `mkdocs build --strict` (with `DJANGO_SETTINGS_MODULE` pointed at
  `tests.conftest_settings`, since `mkdocstrings` imports the package and DRF
  reads settings at import time). Broken links / missing pages fail fast.
- `test` job — matrix Python 3.10–3.14 × Django 4.2/5.0/5.1/5.2/6.0, with the
  Python × Django version-support exclusions baked in. Each cell pins Django via
  `uv pip install --reinstall-package django "django~=X.Y.0"` then runs `pytest`
  (which enforces `--cov-fail-under=100`).
- `examples` job — `make examples`, the example project's own `manage.py test`
  suite, which pytest does not collect and the coverage gate does not measure.

`.github/workflows/release.yml` runs on every push to `main` and publishes only
when the version is new (see *Releasing* below).

`.pre-commit-config.yaml` runs locally on every commit:

- `pre-commit-hooks` basics (trailing whitespace, EOL, YAML, large files)
- `make lint-fix`, `make format`, `make type-check`

If a hook fails, fix the underlying issue and create a **new** commit. Don't `--amend` to chase hook output (that risks losing prior work in pre-existing commits).

---

## Common pitfalls

- **Functions stored as class attributes get bound on instance access.** Use `views.utils.get_class_attr(self, "name")` to retrieve the unbound callable; never read a callable stored on a view via plain `self.attr`.
- **`DataclassSerializer` can't deduce a field type from `Any`.** Use proper types (`str | None = None` for an optional field). It cannot take a partial call either, so a `PATCH` over one is validated whole, as a `PUT` is (`test_service_update_view`'s `test_a_patch_over_a_dataclass_validates_every_field`).
- **An update or delete spec's row is its own target selector's, never `get_object()`'s.** `resolve_mutation_instance` hands the kernel `UNSET` where the spec declares an `instance_selector_spec`, and the kernel's lookup finds the row; the view's object permissions are then asked of it. So `filter_backends` do not narrow the row a `PATCH` or `DELETE` reaches: put tenant scoping in the selector's own queryset. A standalone update or delete view refuses a spec with no target selector at `as_view()`.
- **Don't invent a new filtering DSL.** For list endpoints DRF's `filter_backends` are the default. The one spec-level hook is the kernel `SelectorSpec.filter_set`, a real `django-filter` `FilterSet` applied by the kernel's dispatch; it **replaces** `DjangoFilterBackend` on the list path (guarded at `as_view()` in `views.spec_validation.validate_filter_set_no_backend_conflict`). A target selector's filter reads the route and the query string only, never the body. When a selector returns an aggregate or computed object rather than a queryset, those `?param` values are the selector's `reads`. See `docs/recipes/selector-filtering.md`.
- **Adding a view that dispatches a kernel spec?** Don't reassemble the argument dict or call the kernel's `dispatch` directly: go through `views.mutation.utils.dispatch_mutation_for_spec` (writes) or `selectors.utils.dispatch_kernel_selector` (reads). Both resolve the view's hook chains into a `ViewHooks` carrier and hand off to `dispatch/kernel_edge.py`, the one place a request becomes the kernel's arguments (route captures, the query string and the body, by the kernel's rules) and a refusal becomes DRF's answer (`dispatch/kernel_refusals.py`). A value a view hook or a spec's provider answers outranks the one the Validator produced for the same key. Hook fail-fast validation into `as_view()` through `views.spec_validation.validate_mutation_view_spec` / `validate_selector_view_spec`.
- **A JSON body is checked by the kernel's types first; a form body by the serializer alone.** The edge dispatches `kernel_spec_variant(lenient=True)` only for a body DRF parsed into a `MultiValueDict` (a form or multipart body): its `SerializerValidator` declares each field by name alone, so `"on"` for a boolean, an empty optional field and an unchecked box answer as a bare DRF serializer answers them, every field's refusal at once (`tests/views/test_drf_validation_over_http.py`). A JSON body keeps the kernel's typed check, so a JSON `"true"` is a string, not a boolean. A form body's prefixed spellings of a nested or list field (`v.tenant`, `tags[0]`) reach their field (`tests/views/test_an_undeclared_key_over_http.py`). A key the spec does not declare is dropped at the edge rather than refused, where the kernel's own `dispatch` refuses it.
- **`# ty: ignore[<rule>]`, not `# type: ignore[<rule>]`.** ty has its own pragma syntax and ignores mypy-style comments. The most common rule names are `unresolved-attribute` (for stub-incomplete super calls and dynamic attributes like the `_service_spec` stamp on `@service_action`) and `unused-ignore-comment`.

---

## Releasing

The release pipeline is **merge-to-main triggered**, not tag-triggered.
`.github/workflows/release.yml` runs on every push to `main` and calls
`make release-publish-prepare`. The script in
[`scripts/release-publish.sh`](scripts/release-publish.sh) is the single source
of truth for the flow and behaves as follows:

1. Extract the version from `django_spec_rest/version.py` (the
   single source of truth; `pyproject.toml` declares `dynamic = ["version"]`
   and hatchling reads the value from `version.py` at build time).
2. Check whether `vX.Y.Z` already exists locally or on origin. **If yes →
   short-circuit:** emit `released=false` to `$GITHUB_OUTPUT` and exit 0.
   That is what makes every-merge-to-main safe: non-bumping merges are no-ops.
3. Run `uv run pytest` as a final gate.
4. `uv build` into `dist/`.
5. Extract the `## [X.Y.Z]` section from `CHANGELOG.md` into
   `dist/release-notes.md`.
6. Emit `released=true` so the downstream steps run.

If `released=true`, the workflow then:

- Publishes to PyPI via **OIDC trusted publishing**
  (`pypa/gh-action-pypi-publish`, no token in repo).
- Calls `make release-publish-finalize`, which tags `vX.Y.Z`, pushes the tag,
  and runs `gh release create vX.Y.Z --notes-file dist/release-notes.md
  dist/*.whl dist/*.tar.gz`.
- `mkdocs gh-deploy --force --clean` to `gh-pages` (skipped if `mkdocs.yml`
  is missing).

The previous tag-trigger flow has been removed.

### Cutting a release

The bump itself is driven by
[bump-my-version](https://github.com/callowayproject/bump-my-version) via `uvx`;
configuration lives in `[tool.bumpversion]` in `pyproject.toml`.

```bash
# 1. On a release branch, make sure CHANGELOG.md has the entries you want
#    to ship under ## [Unreleased]. Then bump:
make release-bump VERSION=0.4.1
# This rewrites django_spec_rest/version.py (the single source of
# truth — pyproject.toml is dynamic and reads from it at build time),
# promotes the [Unreleased] block under a dated [0.4.1] section, and
# rewrites the link footer — all driven by the [[tool.bumpversion.files]]
# entries in pyproject.toml.

# 2. Review the diff, commit, open a PR, get it reviewed.
git diff
git commit -am "Release 0.4.1"
git push -u origin release/0.4.1
gh pr create

# 3. Merge to main. release.yml fires on the merge commit, detects the
#    bumped version, runs the full flow, and tags/publishes vX.Y.Z.
```

`release-bump` refuses to run on a dirty tree (bump-my-version's
`allow_dirty = false`), so you don't fold unrelated changes into the
release commit.

For an end-to-end workstation release (e.g. publishing from a developer
machine when CI is broken), `make release-publish` runs prepare → `uv publish`
→ finalize in one shot. Set `DRY_RUN=1` to rehearse without uploading or
pushing.

### One-time setup (manual, by the repo owner)

These steps need to happen once before the first tag push will succeed:

1. **PyPI Trusted Publisher** — sign in to PyPI, open the project settings,
   add a publisher pointing at `Artui/django-spec-rest`, workflow
   `release.yml`, environment `pypi`. (Use a "Pending" publisher if the project
   does not yet exist on PyPI; promote it after the first release.)
2. **GitHub Environment** — create a `pypi` environment under
   `Settings → Environments` (no secrets needed; OIDC handles auth).
3. **GitHub Pages** (only if you publish docs) — under `Settings → Pages`,
   set "Build and deployment" source to "Deploy from a branch", branch
   `gh-pages`, folder `/`. The first tag push that has a `mkdocs.yml` will
   create that branch.

### Manual fallback

If the workflow is unavailable, `uv build && uv publish` still works
(publishing needs a PyPI token in env or `~/.pypirc`). Prefer the tag-driven
path — it keeps tag, version, and PyPI in lockstep.
