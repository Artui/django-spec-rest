"""Every module of the package imports before the app registry is ready.

A project may import ``django_spec_rest`` at the top of an ``AppConfig`` module or an
app's ``__init__``, which Django runs while ``apps.populate()`` is still importing app
configs, or anywhere before ``django.setup()``. A module that imports a concrete Django
model at import time raises ``AppRegistryNotReady`` there. The package is not itself an
installed app, so neither the suite (whose settings are populated before any test runs)
nor the example project would see such an import: this test is what holds the rule
``CLAUDE.md`` states under *Imports inside the package*.

It runs in a subprocess because this process already ran ``django.setup()``, and it
walks every module rather than the package root, because a leaf the root does not
re-export would otherwise go unimported.
"""

from __future__ import annotations

import subprocess
import sys

_PROBE = """
import importlib
import pkgutil

from django.conf import settings

settings.configure(
    SECRET_KEY="x",
    INSTALLED_APPS=[
        "django.contrib.contenttypes",
        "django.contrib.auth",
        "rest_framework",
    ],
)

import django_spec_rest

names = [
    module.name
    for module in pkgutil.walk_packages(django_spec_rest.__path__, "django_spec_rest.")
]
for name in names:
    importlib.import_module(name)
print(len(names))
"""


def test_every_module_imports_before_django_setup() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    # The walk found the package's modules rather than an empty path.
    assert int(result.stdout) > 100
