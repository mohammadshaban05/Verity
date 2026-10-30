"""Smoke test: the package is installed and importable. Tests no behavior."""

import verity


def test_package_imports_with_version() -> None:
    assert isinstance(verity.__version__, str)
    assert verity.__version__
