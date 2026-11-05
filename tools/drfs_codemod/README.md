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
- `--root DIR` (repeatable, default `.`): where a dotted module is looked up
  to read a selector's signature, so the `reads=` it would take can be
  spelled. The module is parsed, never imported.
- `--check`: write nothing; exit 1 while any file would change.
- `--report FILE`: write the report there instead of to stdout.

The count of files changed goes to stderr.

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
- **A name with no counterpart** (`PolymorphicServiceSpec`, `OfflineContract`,
  `TargetGuard`, an input marker). Its import is kept so the module still
  imports; the comment says what replaces it.
- **A `success_status` or `response_finalizer` with no view here**, or on a
  spec built inline in a view rather than bound to a module-level name. Set it
  on the view serving the spec, as the comment says where.

An input serializer is carried over as declared, in a `SerializerValidator`, so
it accepts what it accepted under drfs. An empty PATCH answers as the
project's serializer did: a partial serializer lets it through to the service
and the model, where the kernel's own validator would answer 400.

The output is not formatted: run the project's formatter after the codemod.

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
