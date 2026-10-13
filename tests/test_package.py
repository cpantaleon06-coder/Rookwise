"""Proves that pytest runs and that the `rookwise` package (source in core/) imports."""

import rookwise


def test_package_imports():
    assert isinstance(rookwise.__version__, str)
