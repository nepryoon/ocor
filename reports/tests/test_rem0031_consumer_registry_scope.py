"""PO REM-0031-REGISTRY-CONSUMER-SCOPE (option 1): exact registry-seeding-only guard.

The six authorized consumer modules may change only where they write the
IdentityRegistry or construct it: post-construction ``register`` calls become
composition seeding. Same test functions, identical ``assert`` nodes,
``pytest.raises`` calls and parametrization decorators, identical seeded
``IdentityRecord`` expressions, changes confined to the named functions, and an
exact pinned diff; any other change fails this guard.
"""
from __future__ import annotations

import ast
import difflib
import hashlib
import json
import subprocess
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = '60afecfb0428350b552f77861455b695ebbd24f1'
TASKS = 'ocor-runtime/tests/tasks/'
ALLOWED = {
    TASKS + 'test_ocor_dev_0043.py': {'identities'},
    TASKS + 'test_ocor_dev_0044.py': {'identities', 'break_glass_identities'},
    TASKS + 'test_ocor_dev_0058.py': {'workflow'},
    TASKS + 'test_ocor_dev_rem_0024.py': {'registry'},
    TASKS + 'test_ocor_dev_rem_0027.py': {'Harness.__init__'},
    TASKS + 'test_ocor_dev_rem_0028.py': {
        'directory',
        'test_real_dual_role_holder_still_cannot_fill_two_role_slots',
        'test_valid_distinct_role_assignment_is_independent_of_signature_order',
        'test_distinct_role_matching_agrees_with_exhaustive_assignment_oracle',
    },
}
# The only register() calls left: the REM-0024 update attempts that must still
# raise IdentityConflictError (immutability is checked before the Q1 refusal).
REMAINING_REGISTER = {TASKS + 'test_ocor_dev_rem_0024.py': 2}
PINNED_DIFF_SHA256 = 'e06ea00b6b3c4c5eddecc0214a741693087cadd48e4f5dfee10c7f9c280a6a05'


def dump(node: ast.AST) -> str:
    return ast.dump(node, include_attributes=False)


def baseline(path: str) -> str:
    return subprocess.check_output(['git', 'show', f'{BASE}:{path}'], cwd=ROOT, text=True, timeout=15)


def functions(tree: ast.AST, prefix: str = '') -> dict[str, ast.AST]:
    result: dict[str, ast.AST] = {}
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result[prefix + node.name] = node
            result.update(functions(node, prefix + node.name + '.'))
        elif isinstance(node, ast.ClassDef):
            result.update(functions(node, prefix + node.name + '.'))
    return result


def is_call(node: ast.AST, name: str) -> bool:
    return isinstance(node, ast.Call) and (
        (isinstance(node.func, ast.Name) and node.func.id == name)
        or (isinstance(node.func, ast.Attribute) and node.func.attr == name)
    )


def protected(tree: ast.AST) -> dict[str, list[str]]:
    defs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    return {
        'tests': sorted(name for name in functions(tree) if name.rsplit('.', 1)[-1].startswith('test_')),
        'signatures': [dump(n.args) for n in defs if n.name.startswith('test_')],
        'assertions': [dump(n) for n in ast.walk(tree) if isinstance(n, ast.Assert)],
        'raises': [dump(n) for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and n.func.value.id == 'pytest' and n.func.attr == 'raises'],
        'decorators': [dump(d) for n in defs for d in n.decorator_list],
    }


def changed_lines(before: str, after: str) -> dict[str, list[str]]:
    removed, added = [], []
    for line in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm='', n=0):
        if line.startswith(('---', '+++', '@@')):
            continue
        (removed if line.startswith('-') else added).append(line[1:])
    return {'removed': removed, 'added': added}


def compare(path: str, before: str, after: str) -> dict[str, object]:
    old, new = ast.parse(before), ast.parse(after)
    assert protected(old) == protected(new), 'test/assert/pytest.raises/decorator changed'
    original, modified = functions(old), functions(new)
    assert original.keys() == modified.keys(), 'function inventory changed'
    changed = {name for name in original if dump(original[name]) != dump(modified[name])}
    assert changed <= ALLOWED[path], f'non-authorized function changed: {sorted(changed - ALLOWED[path])}'
    outside = [dump(n) for n in old.body if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    assert outside == [dump(n) for n in new.body if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))], 'module-level statement changed'
    records = lambda tree: Counter(dump(n) for n in ast.walk(tree) if is_call(n, 'IdentityRecord'))  # noqa: E731
    assert records(old) == records(new), 'seeded IdentityRecord expressions changed'
    registers = sum(1 for n in ast.walk(new) if is_call(n, 'register'))
    assert registers == REMAINING_REGISTER.get(path, 0), 'post-construction registry write remains or was added'
    return {
        'path': path,
        'before_sha256': hashlib.sha256(before.encode()).hexdigest(),
        'after_sha256': hashlib.sha256(after.encode()).hexdigest(),
        'changed_functions': sorted(changed),
        'test_functions': len(protected(old)['tests']),
        'assertions': len(protected(old)['assertions']),
        'pytest_raises': len(protected(old)['raises']),
        'decorators': len(protected(old)['decorators']),
        'identity_records': sum(records(old).values()),
        'remaining_register_calls': registers,
    }


def diff_digest(texts: dict[str, tuple[str, str]]) -> str:
    diff = {path: changed_lines(before, after) for path, (before, after) in sorted(texts.items())}
    return hashlib.sha256(json.dumps(diff, sort_keys=True).encode()).hexdigest()


def check(texts: dict[str, tuple[str, str]]) -> dict[str, object]:
    files = [compare(path, before, after) for path, (before, after) in sorted(texts.items())]
    digest = diff_digest(texts)
    assert digest == PINNED_DIFF_SHA256, f'diff differs from the pinned seeding-only diff: {digest}'
    return {'status': 'PASS', 'base': BASE, 'pinned_diff_sha256': digest, 'files': files}


def current() -> dict[str, tuple[str, str]]:
    return {path: (baseline(path), (ROOT / path).read_text()) for path in ALLOWED}


class ConsumerRegistryScope(unittest.TestCase):
    def test_exact_seeding_only_diff(self) -> None:
        result = check(current())
        self.assertEqual(result['status'], 'PASS')

    def test_guard_rejects_any_protected_or_unrelated_change(self) -> None:
        texts = current()
        for path, (before, after) in texts.items():
            mutations = [
                after + '\nUNRELATED = True\n',
                after.replace('assert ', 'assert False and ', 1),
                after.replace('pytest.raises(', 'pytest.warns(', 1),
                after.replace('def test_', 'def test_changed_', 1),
                after.replace('@pytest.mark.parametrize(', '@pytest.mark.changed(', 1),
                after.replace("'status': 'ACTIVE'", "'status': 'SUSPENDED'", 1).replace('"status": "ACTIVE"', '"status": "SUSPENDED"', 1),
                after.replace('IdentityRegistry(', 'IdentityRegistry(\n', 1) + '\n# trailing\n',
                after.rstrip('\n') + '\n\n\ndef helper_added():\n    return None\n',
            ]
            for mutated in mutations:
                if mutated == after:
                    continue
                with self.subTest(path=path, mutation_sha256=hashlib.sha256(mutated.encode()).hexdigest()):
                    with self.assertRaises(AssertionError):
                        check({**texts, path: (before, mutated)})

    def test_guard_rejects_a_reintroduced_post_construction_write(self) -> None:
        texts = current()
        path = TASKS + 'test_ocor_dev_0044.py'
        before, after = texts[path]
        mutated = after.replace(
            '    return registry\n',
            '    registry.register(IdentityRecord(canonical_id="urn:ocor:human:z", attributes={"roles": ""}))\n    return registry\n',
            1,
        )
        self.assertNotEqual(mutated, after)
        with self.assertRaises(AssertionError):
            check({**texts, path: (before, mutated)})


if __name__ == '__main__':
    print(json.dumps(check(current()), indent=2, sort_keys=True))
