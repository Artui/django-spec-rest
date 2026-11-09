# drfs_codemod

Rewrites a project's `djangorestframework-services` (drfs 0.62.0) imports and
spec declarations onto `django-service-specs` and `django-spec-rest`, in
place, and reports every site it leaves. What it changes and what it does not
are on the docs page,
[Moving from djangorestframework-services](https://artui.github.io/django-spec-rest/moving-from-drfs/#the-codemod).

It is not part of the wheel. Run it from a clone of this repository, in an
environment with `libcst` and `django-service-specs` installed (this
repository's dev environment has both):

```bash
PYTHONPATH=tools python -m drfs_codemod path/to/project --root path/to/project
```

## Arguments

- `PATH...`: files, or directories searched for `.py` files. Hidden
  directories, `node_modules`, `site-packages` and `__pycache__` are skipped
  unless named.
- `--root DIR` (repeatable, default `.`): where a dotted module is looked up,
  to read a selector's signature, so the `reads=` it would take can be
  spelled, and to follow a view's absolute import of its spec. The module is
  parsed, never imported.
  The root is the directory absolute imports start from, usually the parent of
  the top package: for `from backend.shop.specs import x`, the directory
  holding `backend/`. A wrong root gives no error: no import is found, so the
  run reads as "no view in this run" for every spec.
- `--check`: write nothing; exit 1 while any file would change. It reports what
  a run would move and leave, at each file's lines as they stand.
- `--report FILE`: write the report there instead of to stdout.

The count of files changed goes to stderr. A file that cannot be parsed, or is
not UTF-8, stops the run with exit 2 before anything is written, and stderr
names it: name the paths around it.

## The report

One line per site left, `path:line: reason`, in the order of the files and
their lines, then a count. Every site also gets a comment above its statement:

```python
# drfs-codemod: selector=by_pk takes by name what drfs filled from the route or query string; ...
target = SelectorSpec(kind=SelectorKind.RETRIEVE, selector=by_pk)
```

A line names the file as it stands after the run, so it points at the
statement under its comment. A second run writes nothing and reports the same
sites, because it reads them from the comments: a site stays in the report
until its comment is deleted. Delete each once it is dealt with.

## Finishing a site by hand

- **A `reads=` from a selector's signature.** The comment spells it, as
  `reads=Parameters.of(Parameter("pk", "integer", required=True))`. Check each
  name is one the caller sends, not one a provider or the server fills, add
  it to the selector, and import `Parameter` and `Parameters` from
  `django_service_specs`.
- **A drfs `reads=[UrlKwarg(...), QueryParam(...)]`.** Kept as it was, with
  its import: replace it with the `Parameter` declaring each read's type.
- **A name with no counterpart** (`TargetGuard`, an input marker) **or whose parts
  have several** (`OfflineContract`, `ArgumentBinding`). Its import is kept so the module
  still imports; the comment says what replaces it, and the moving page's "Declaring a
  spec" places each part.
- **A `PolymorphicServiceSpec`**, whose counterpart is a different shape:
  `DiscriminatedAction(discriminator=, specs=)`, for an endpoint that must keep one URL,
  without `permission_strategy=`. Its import is kept and the comment names the type; the
  `specs` become kernel specs by the rest of this page, and the moving page's "Declaring
  a spec" places the rest.
- **A `success_status` or `response_finalizer` with no view found**, or on a
  spec built inline in a view rather than bound to a module-level name. Set it
  on the view serving the spec, as the comment says where, and say the value
  the comment carries. A view in another module is followed where that is
  certain, as [below](#a-view-in-another-module), and otherwise the comment ends
  with why it was not.

An input serializer is carried over as declared, in a `SerializerValidator`, so
it accepts what it accepted under drfs. An empty PATCH answers as the
project's serializer did: a partial serializer lets it through to the service
and the model, where the kernel's own validator would answer 400.

The output is not formatted: run the project's formatter after the codemod.

## A view in another module

A kernel spec has no seat for `success_status` or `response_finalizer`, so they
move to the view, and in a `specs/` plus `views/` layout the view is in another
file. All the files named in one run are read together, and an answer follows
the spec's import into the view when all of this holds:

- **The spec and the view are both in the run.** Over `specs/` alone the note
  is written; over `views/` alone the spec is not touched.
- **One other module serves the spec**, by `spec = name`, an `action_specs`
  entry or `@service_action(name)`, and has no other use of the name. Several
  views in that module each take it, as views in the spec's own module do.
- **It is imported by its own name**, as `from specs.x import y`, relatively,
  through a package's unaliased re-export (`from specs import y`), or through a
  module, however that module is named: `from specs import x`,
  `import specs.x as s`, `import specs.x`. An absolute import is found under
  `--root`.
- **A registration is not a use.** A module may also pass the spec to
  `<registry>.register(...)`, where `<registry>` is a name bound once at module
  level to a `SpecRegistry(...)` call, with `SpecRegistry` imported from drfs
  (or the kernel). A registry is read for an agent, never to route a request, so
  that module neither serves the spec nor blocks it. A module that only
  registers a spec leaves the plain note when nothing else serves it. Any other
  `.register(...)` (`admin.site.register(x)`, a registry built or imported
  from somewhere else, the spec inside a larger expression) is a use like any
  other and blocks.
- **No view is in the spec's own module.** Then the answer stays with that view.
- **The value resolves in the view.** One naming nothing moves as written. A
  name, or a dotted name such as `status.HTTP_201_CREATED`, brings its import:
  the spec module's own absolute import, or, for a name the spec module defines,
  an import of it from there (not through a re-export, which holds only the spec).

Anything else is left with the note, which ends in why: a spec imported by two
modules, under an alias, by a star import or inside a function; one its own
module reuses or binds twice; a lambda or a call naming anything, a builtin, a
name the spec module imports relatively or from drfs. A test module (`test_*.py`,
`*_test.py`, `tests.py`, `conftest.py`, or under `tests/`) reading a spec does not
count as a use; a view declared in one does.

The view can refuse. If it already declares that answer, or a value's name means
something else there, the view gets a comment saying so and the spec's note stays,
so an answer is never removed from a spec without arriving or being named on it.
A view is written before the spec it empties.

A spec's note says where its answer went, and a module outside the run serving
that spec still has to declare it. A name it imported for the value alone may be
left unused in the spec's module; the project's linter finds it. A run only sees
what is still on a spec, so an earlier run's note is not followed: finish that one
by hand.

## The import map

`import_map.py` lists every name drfs 0.62.0 lets a project import, keyed by
the module it was imported from, and where each goes, or why it goes nowhere.
It is generated, never edited:

```bash
python tools/drfs_codemod/generate_import_map.py \
    --drfs <site-packages>/rest_framework_services \
    --kernel <site-packages>/django_service_specs \
    --rest django_spec_rest
ruff format tools/drfs_codemod/import_map.py
```

## Tests

`tests/tools/` runs in `make test`. The coverage gate measures
`django_spec_rest` alone, so these tests neither count toward it nor dilute
it.
