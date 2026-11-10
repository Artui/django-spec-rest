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
    assert int(result.stdout) > 50
