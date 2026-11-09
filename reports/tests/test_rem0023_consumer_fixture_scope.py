"""PO REM-0023-DENIAL-AUDIT-CONSUMER-FIXTURES: exact constructor-only guard.

NCP-U11-REM0023-CONSUMER-GUARD (2026-11-09, option 1): for test_ocor_dev_0055.py the
guard also removes exactly the difference of the NORMATIVE-CONFORMANCE-PLAN point 5
choice for NCP-U11 (NCR-MEMORY-003, OCOR-DEV-REM-0059) -- the three cases taken out of
INVALID_DELETIONS, compared by value with those of BASE, the DECLARED_DELETIONS
assignment and the positive deletion test, both compared byte for byte with the texts
fixed below -- and nothing else.

NCP-U11-ADMISSION-QUOTA-COMPOSITION (2026-11-09, option A1) and
NCP-U11-ADMISSION-QUOTA-WORLDS (2026-11-09, option 1): every
MemoryAdmissionService call of both files must also carry exactly the argument
``quota=`` with the explicit test quota port, compared byte for byte with the
text fixed below; the guard removes exactly that argument and nothing else.
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
BASE = '7cfb60d195c64c1ded0f3d5ea0bd92df565552c1'
FILES = [f'ocor-runtime/tests/tasks/test_ocor_dev_{n}.py' for n in ('0054', '0055')]


# NCP-U11 (point 5 table): the three cases moved from INVALID_DELETIONS, by value at BASE.
NCP_U11_MOVED = [
    ("latest only", {"deletion_scope": "LATEST_VERSION"}, "UNSUPPORTED_CAPABILITY", "DELETION_SCOPE_UNSUPPORTED"),
    ("project scope", {"deletion_scope": "PROJECT_SCOPE"}, "UNSUPPORTED_CAPABILITY", "DELETION_SCOPE_UNSUPPORTED"),
    ("principal scope", {"deletion_scope": "PRINCIPAL_SCOPE"}, "UNSUPPORTED_CAPABILITY", "DELETION_SCOPE_UNSUPPORTED"),
]
NCP_U11_DECLARED = (
    'DECLARED_DELETIONS = [\n'
    '    ("latest only", {"deletion_scope": "LATEST_VERSION"}),\n'
    '    ("project scope", {"deletion_scope": "PROJECT_SCOPE"}),\n'
    '    ("principal scope", {"deletion_scope": "PRINCIPAL_SCOPE"}),\n'
    ']'
)
NCP_U11_POSITIVE_NAME = 'test_declared_deletion_scopes_forget_the_item_through_the_saga'
NCP_U11_POSITIVE = (
    '@pytest.mark.parametrize(("label", "changes"), DECLARED_DELETIONS, ids=[c[0] for c in DECLARED_DELETIONS])\n'
    'def test_declared_deletion_scopes_forget_the_item_through_the_saga(label: str, changes: dict[str, Any]) -> None:\n'
    '    world = unit_world()\n'
    '    world.admit("item", TEXT)\n'
    '    body = world.body(reason_code="AUTHORIZED_REQUEST", deletion_scope="ALL_VERSIONS")\n'
    '    body.update(changes)\n'
    '    receipt = world.lifecycle.request_deletion("item", body, binding=t52.binding())\n'
    '    assert receipt.to_mapping()["status"] == "COMPLETED" and receipt.lifecycle_status == "DELETED"\n'
    '    assert world.status("item") == "DELETED" and world.tombstones.latest_epoch() == 1\n'
    '    assert denials(world) == []'
)


# NCP-U11-ADMISSION-QUOTA-WORLDS option 1: the explicit test quota port, byte for byte.
NCP_U11_QUOTA_PORT = 'base.RecordingAdmissionQuota()'


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


def _module_assign(tree: ast.Module, name: str) -> list[ast.Assign]:
    return [n for n in tree.body if isinstance(n, ast.Assign) and len(n.targets) == 1
            and isinstance(n.targets[0], ast.Name) and n.targets[0].id == name]


def strip_ncp_u11(old: ast.Module, new: ast.Module, after: str) -> ast.Module:
    """Remove exactly the authorised NCP-U11 difference from ``new`` (a copy), or fail."""

    declared = _module_assign(new, 'DECLARED_DELETIONS')
    positive = [n for n in new.body if isinstance(n, ast.FunctionDef) and n.name == NCP_U11_POSITIVE_NAME]
    if not declared and not positive and not _module_assign(old, 'DECLARED_DELETIONS'):
        return new  # the file without the NCP-U11 move: nothing to remove
    assert len(declared) == 1 and len(positive) == 1, 'NCP-U11 difference incomplete'
    assert ast.get_source_segment(after, declared[0]) == NCP_U11_DECLARED, 'DECLARED_DELETIONS differs from the authorised text'
    function = positive[0]
    assert function.decorator_list, 'NCP-U11 positive test lost its parametrisation'
    text = '\n'.join(after.splitlines()[function.decorator_list[0].lineno - 1:function.end_lineno])
    assert text == NCP_U11_POSITIVE, 'NCP-U11 positive test differs from the authorised text'
    old_invalid, new_invalid = _module_assign(old, 'INVALID_DELETIONS'), _module_assign(new, 'INVALID_DELETIONS')
    assert len(old_invalid) == 1 and len(new_invalid) == 1, 'INVALID_DELETIONS missing'
    old_list, new_list = old_invalid[0].value, new_invalid[0].value
    assert isinstance(old_list, ast.List) and isinstance(new_list, ast.List), 'INVALID_DELETIONS is not a list'

    def literal(node: ast.expr) -> object:
        try:
            return ast.literal_eval(node)
        except ValueError:
            return None

    moved = [e for e in old_list.elts if literal(e) in [tuple(m) for m in NCP_U11_MOVED]]
    assert [literal(e) for e in moved] == [tuple(m) for m in NCP_U11_MOVED], 'moved cases differ by value from BASE'
    assert [dump(e) for e in new_list.elts] == [dump(e) for e in old_list.elts if e not in moved], \
        'INVALID_DELETIONS changed beyond the three authorised cases'
    assert [m[:2] for m in NCP_U11_MOVED] == literal(declared[0].value), 'DECLARED_DELETIONS do not match the moved cases'
    new_list.elts = copy.deepcopy(old_list.elts)
    new.body = [n for n in new.body if n is not declared[0] and n is not function]
    return new


def strip_quota_port(new: ast.Module, after: str) -> ast.Module:
    """Remove the authorised ``quota=`` argument from every MemoryAdmissionService call, or fail."""

    calls = [n for n in ast.walk(new) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'MemoryAdmissionService']
    assert calls, 'no MemoryAdmissionService call'
    for call in calls:
        quotas = [k for k in call.keywords if k.arg == 'quota']
        assert len(quotas) == 1, 'a MemoryAdmissionService call lacks the quota port'
        assert ast.get_source_segment(after, quotas[0].value) == NCP_U11_QUOTA_PORT, 'quota differs from the authorised text'
        call.keywords.remove(quotas[0])
    return new


def compare(before: str, after: str) -> dict[str, object]:
    old = ast.parse(before)
    new = strip_ncp_u11(old, strip_quota_port(ast.parse(after), after), after)
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
            # NCP-U11-REM0023-CONSUMER-GUARD option 1: a fourth case out of INVALID_DELETIONS, a case out of
            # DECLARED_DELETIONS, a weakened positive test, a moved case kept with another value.
            mutations += [
                after.replace('    ("not a trigger", {"reason_code": "BECAUSE"}, "MEMORY_SCHEMA_INVALID", "FORGETTING_TRIGGER_INVALID"),\n', '', 1),
                after.replace('    ("principal scope", {"deletion_scope": "PRINCIPAL_SCOPE"}),\n', '', 1),
                after.replace('world.tombstones.latest_epoch() == 1\n    assert denials(world) == []', 'world.tombstones.latest_epoch() >= 0\n    assert denials(world) == []', 1),
                after.replace('DECLARED_DELETIONS = [\n', 'DECLARED_DELETIONS = [\n    ("all versions", {"deletion_scope": "ALL_VERSIONS"}),\n', 1),
            ]
            # NCP-U11-ADMISSION-QUOTA-WORLDS option 1: quota removed, another quota text, another argument
            # of the same call changed, an argument added next to the quota.
            quota_mutations = [
                after.replace('            quota=base.RecordingAdmissionQuota(),\n', '', 1),
                after.replace('quota=base.RecordingAdmissionQuota()', 'quota=RecordingAdmissionQuota()', 1),
                after.replace('quota=base.RecordingAdmissionQuota()', 'quota=base.RecordingAdmissionQuota() or None', 1),
                after.replace('}),\n            quota=base.RecordingAdmissionQuota(),', '}, content_schemas=frozenset()),\n            quota=base.RecordingAdmissionQuota(),', 1),
                after.replace('quota=base.RecordingAdmissionQuota(),', 'quota=base.RecordingAdmissionQuota(), policy_bundle=None,', 1),
            ]
            assert all(m != after for m in quota_mutations), 'a quota mutation does not apply'
            mutations += quota_mutations
            for mutated in mutations:
                if mutated == after:
                    continue
                with self.subTest(path=path, mutation_sha256=hashlib.sha256(mutated.encode()).hexdigest()):
                    with self.assertRaises(AssertionError):
                        compare(before, mutated)


if __name__ == '__main__':
    unittest.main()
