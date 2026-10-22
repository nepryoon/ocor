"""PO REM-0023-DENIAL-AUDIT-CONSUMER-FIXTURES: exact constructor-only guard."""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = '7cfb60d195c64c1ded0f3d5ea0bd92df565552c1'
FILES = [f'ocor-runtime/tests/tasks/test_ocor_dev_{n}.py' for n in ('0054', '0055')]


def dump(node: ast.AST) -> str:
    return ast.dump(node, include_attributes=False)


def baseline(path: str) -> str:
    return subprocess.check_output(['git', 'show', f'{BASE}:{path}'], cwd=ROOT, text=True, timeout=15)


def protected(tree: ast.AST) -> dict[str, list[str]]:
    return {
        'tests': [dump(n) for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith('test_')],
        'assertions': [dump(n) for n in ast.walk(tree) if isinstance(n, ast.Assert)],
        'raises': [dump(n) for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and n.func.value.id == 'pytest' and n.func.attr == 'raises'],
        'decorators': [dump(d) for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for d in n.decorator_list],
    }


class StripWiring(ast.NodeTransformer):
    """Only these exact AST additions may disappear from the original tree."""

    def visit_Import(self, node: ast.Import) -> ast.AST | None:
        if dump(node) == dump(ast.parse('import test_ocor_dev_rem_0023 as denial').body[0]):
            return None
        return node

    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.AST:
        if node.module == 'ocor_runtime.memory.model':
            node.names = [n for n in node.names if n.name != 'MemoryAdmissionAuditSink' or n.asname is not None]
        return node

    def visit_arguments(self, node: ast.arguments) -> ast.AST:
        pairs = list(zip(node.kwonlyargs, node.kw_defaults, strict=True))
        node.kwonlyargs = [a for a, _ in pairs if a.arg != 'admission_audit']
        node.kw_defaults = [d for a, d in pairs if a.arg != 'admission_audit']
        return self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> ast.AST | None:
        if dump(node) == dump(ast.parse('self.admission_audit = admission_audit').body[0]):
            return None
        return self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> ast.AST:
        call = ast.unparse(node.func)
        for kw in list(node.keywords):
            value = ast.unparse(kw.value)
            if call == 'MemoryAdmissionService' and kw.arg == 'audit' and value in {'admission_audit', 'clone.admission_audit'}:
                node.keywords.remove(kw)
            elif call in {'CWorld', 'World'} and kw.arg == 'admission_audit' and value in {'r.Audit()', 't52.Audit()', 'denial.SchemaPostgresAudit(self.dsn, schema)'}:
                node.keywords.remove(kw)
        return self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> ast.AST:
        # The 0054 live port factory must install the real PostgreSQL sink.
        pairs = [(k, v) for k, v in zip(node.keys, node.values, strict=True) if not (
            isinstance(k, ast.Constant) and k.value == 'admission_audit'
            and ast.unparse(v) == 'denial.SchemaPostgresAudit(self.dsn, schema)')]
        node.keys, node.values = [k for k, _ in pairs], [v for _, v in pairs]
        return self.generic_visit(node)


def compare(before: str, after: str) -> dict[str, object]:
    old, new = ast.parse(before), ast.parse(after)
    assert protected(old) == protected(new), 'test/assert/pytest.raises/decorator changed'
    def functions(tree: ast.Module) -> dict[str, str]:
        result = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                result[node.name] = dump(node)
            elif isinstance(node, ast.ClassDef):
                for method in node.body:
                    if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        result[node.name + '.' + method.name] = dump(method)
        return result
    original, modified = functions(old), functions(new)
    assert original.keys() == modified.keys(), 'function inventory changed'
    allowed = ({'CWorld.__init__', 'unit_world', 'Backends._ports', 'Backends.fresh'}
               if any(isinstance(n, ast.ClassDef) and n.name == 'CWorld' for n in old.body)
               else {'World.__init__', 'unit_world', 'Backends.world'})
    assert {k for k in original if original[k] != modified[k]} <= allowed, 'non-authorized method changed' 
    assert dump(old) == dump(StripWiring().visit(copy.deepcopy(new))), 'diff outside explicit audit constructor/fixture wiring'
    fixture_calls = [n for c in new.body if isinstance(c, ast.ClassDef) for n in ast.walk(c)]
    admissions = [n for n in fixture_calls if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'MemoryAdmissionService']
    assert admissions and all(any(k.arg == 'audit' for k in n.keywords) for n in admissions), 'explicit admission audit wiring missing'
    ctor = next(n for n in ast.walk(new) if isinstance(n, ast.FunctionDef) and n.name == '__init__' and any(a.arg == 'admission_audit' for a in n.args.kwonlyargs))
    pairs = dict(zip((a.arg for a in ctor.args.kwonlyargs), ctor.args.kw_defaults, strict=True))
    assert pairs['admission_audit'] is None, 'audit is a required port, no volatile fallback'
    arg = next(a for a in ctor.args.kwonlyargs if a.arg == 'admission_audit')
    assert ast.unparse(arg.annotation) == 'MemoryAdmissionAuditSink', 'explicit port type required'
    def digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()
    return {'status': 'PASS', 'before_sha256': digest(before), 'after_sha256': digest(after), 'protected_ast_sha256': digest(json.dumps(protected(old), sort_keys=True)), 'test_functions': len(protected(old)['tests']), 'assertions': len(protected(old)['assertions']), 'pytest_raises': len(protected(old)['raises']), 'decorators': len(protected(old)['decorators']), 'all_other_ast_unchanged': True}


class ConsumerFixtureScope(unittest.TestCase):
    def test_exact_allowed_fixture_diff_and_required_wiring(self) -> None:
        for path in FILES:
            with self.subTest(path=path):
                compare(baseline(path), (ROOT / path).read_text())

    def test_guard_rejects_any_protected_or_unrelated_change(self) -> None:
        for path in FILES:
            before, after = baseline(path), (ROOT / path).read_text()
            mutations = [after + '\nUNRELATED = True\n', after.replace('assert ', 'assert False and ', 1), after.replace('pytest.raises(', 'pytest.warns(', 1), after.replace('def test_', 'def test_changed_', 1), after.replace('@pytest.mark.parametrize(', '@pytest.mark.changed(', 1)]
            for mutated in mutations:
                if mutated == after:
                    continue
                with self.subTest(path=path, mutation_sha256=hashlib.sha256(mutated.encode()).hexdigest()):
                    with self.assertRaises(AssertionError):
                        compare(before, mutated)


if __name__ == '__main__':
    unittest.main()
