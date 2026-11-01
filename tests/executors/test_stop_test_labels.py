"""The docker stop test labels its container like vigild does (no Docker needed)."""

from __future__ import annotations

import ast
from pathlib import Path

from tests.executors import test_runtime_stop_docker as mod

SRC = Path(mod.__file__).read_text()


def _func(name: str) -> ast.FunctionDef:
    for node in ast.walk(ast.parse(SRC)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(name)


def _labels(fn: ast.FunctionDef) -> ast.Dict:
    for node in ast.walk(fn):
        if isinstance(node, ast.keyword) and node.arg == "labels":
            assert isinstance(node.value, ast.Dict)
            return node.value
    raise AssertionError("no labels kwarg")


def test_stop_test_spreads_instance_labels() -> None:
    d = _labels(_func("test_stop_kills_the_sessions_container"))
    assert None in d.keys
    spread = d.values[d.keys.index(None)]
    assert isinstance(spread, ast.Call)
    assert isinstance(spread.func, ast.Name) and spread.func.id == "instance_labels"


def test_unlabelled_test_has_only_session_label() -> None:
    names = [n.name for n in ast.parse(SRC).body if isinstance(n, ast.FunctionDef)]
    assert any("without_instance_label" in n for n in names)
    d = _labels(_func("test_stop_spares_container_without_instance_label"))
    assert None not in d.keys


def test_both_docker_tests_exist() -> None:
    assert callable(mod.test_stop_kills_the_sessions_container)
    assert callable(mod.test_stop_spares_container_without_instance_label)
