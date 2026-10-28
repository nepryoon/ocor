"""PO REM-0037-0006-NETWORK-RESIDUE-DISPOSITION (2026-10-28): exact teardown-only guard.

The sealed test ``test_missing_pinned_image_cannot_fall_back_to_public_pull`` of
OCOR-DEV-0006 may gain only the teardown of the Compose project it creates, in a
``finally`` block. Tests, asserts, inputs, conditions and markers stay identical.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = '9fe22aef11fef1434430a3e253d92b257a07067b'
PATH = 'ocor-runtime/tests/tasks/test_ocor_dev_0006.py'
SEALED_SHA256 = 'f53f983dd59d7bcf9e8191c4cd8c58f8673220a2d4341eb2490055a11e62e15b'
TEST = 'test_missing_pinned_image_cannot_fall_back_to_public_pull'
TEARDOWN = '''subprocess.run(
    ["docker", "compose", "-p", "ocor-missing-image-negative", "-f", str(missing), "down", "--remove-orphans"],
    capture_output=True,
    text=True,
    check=False,
    timeout=120,
)'''


def dump(node: ast.AST) -> str:
    return ast.dump(node, include_attributes=False)


def baseline() -> str:
    text = subprocess.check_output(['git', 'show', f'{BASE}:{PATH}'], cwd=ROOT, text=True, timeout=15)
    assert hashlib.sha256(text.encode()).hexdigest() == SEALED_SHA256, 'baseline is not the sealed 0006 test'
    return text


def walk(node: ast.AST):
    """Depth-first, source-ordered walk: nesting under ``try`` keeps the order."""
    yield node
    for child in ast.iter_child_nodes(node):
        yield from walk(child)


def protected(tree: ast.AST) -> dict[str, list[str]]:
    return {
        'tests': [n.name for n in walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith('test_')],
        'assertions': [dump(n) for n in walk(tree) if isinstance(n, ast.Assert)],
        'raises': [dump(n) for n in walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and n.func.value.id == 'pytest' and n.func.attr == 'raises'],
        'conditions': [dump(n.test) for n in walk(tree) if isinstance(n, (ast.If, ast.While, ast.IfExp))],
        'decorators': [dump(d) for n in walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) for d in n.decorator_list],
    }


class StripTeardown(ast.NodeTransformer):
    """Only the exact ``try``/``finally`` teardown of the target test may disappear."""

    def __init__(self) -> None:
        self.stripped = 0
        self.expected = [dump(ast.parse(TEARDOWN).body[0])]

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        if node.name != TEST:
            return node
        body: list[ast.stmt] = []
        for stmt in node.body:
            if (isinstance(stmt, ast.Try) and not stmt.handlers and not stmt.orelse
                    and [dump(s) for s in stmt.finalbody] == self.expected):
                body.extend(stmt.body)
                self.stripped += 1
            else:
                body.append(stmt)
        node.body = body
        return node


def compare(before: str, after: str) -> dict[str, object]:
    old, new = ast.parse(before), ast.parse(after)
    assert protected(old) == protected(new), 'test/assert/pytest.raises/condition/decorator changed'
    stripper = StripTeardown()
    stripped = stripper.visit(copy.deepcopy(new))
    assert stripper.stripped == 1, 'exact finally teardown of the Compose project missing'
    assert dump(old) == dump(stripped), 'diff outside the authorized teardown'

    def digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()
    return {'status': 'PASS', 'before_sha256': digest(before), 'after_sha256': digest(after),
            'protected_ast_sha256': digest(json.dumps(protected(old), sort_keys=True)),
            'test_functions': len(protected(old)['tests']), 'assertions': len(protected(old)['assertions']),
            'decorators': len(protected(old)['decorators']), 'all_other_ast_unchanged': True}


class TeardownScope(unittest.TestCase):
    def test_exact_teardown_only_diff(self) -> None:
        print(json.dumps(compare(baseline(), (ROOT / PATH).read_text()), sort_keys=True))

    def test_guard_rejects_any_other_change(self) -> None:
        before, after = baseline(), (ROOT / PATH).read_text()
        mutations = [
            before,
            after + '\nUNRELATED = True\n',
            after.replace('assert ', 'assert False and ', 1),
            after.replace('def test_', 'def test_changed_', 1),
            after.replace('@pytest.mark.parametrize(', '@pytest.mark.changed(', 1),
            after.replace('"--remove-orphans"', '"--remove-orphans", "--volumes"', 1),
            after.replace('timeout=120', 'timeout=600', 1),
            after.replace('pull_policy: never', 'pull_policy: missing', 1),
            after.replace('"up", "--detach"', '"up"', 1),
            after.replace('    finally:\n', '    except Exception:\n        pass\n    finally:\n', 1),
            after.replace(TEST + '(tmp_path: Path):', TEST + '(tmp_path: Path):\n    import os', 1),
        ]
        for mutated in mutations:
            self.assertNotEqual(mutated, after)
            with self.subTest(mutation_sha256=hashlib.sha256(mutated.encode()).hexdigest()):
                with self.assertRaises(AssertionError):
                    compare(before, mutated)


if __name__ == '__main__':
    unittest.main()
