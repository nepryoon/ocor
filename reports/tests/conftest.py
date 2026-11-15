"""Mechanical marker for reports tests that need the real disposable stack.

A test is marked ``requires_live_stack`` when its own source contains a call
to ``_require_docker(`` or the sentence ``the real stack is mandatory``.
The state-only CI path selects ``reports/tests`` and excludes that marker.
"""

from __future__ import annotations

import inspect

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "requires_live_stack: test needs the real disposable stack",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    del config
    for item in items:
        function = getattr(item, "obj", None)
        if function is None:
            continue
        try:
            source = inspect.getsource(function)
        except (OSError, TypeError):
            continue
        if "_require_docker(" in source or "the real stack is mandatory" in source:
            item.add_marker(pytest.mark.requires_live_stack)
