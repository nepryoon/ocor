"""REM-0029: teardown must prove absence; failure injection is local only."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('reset_rem0029', ROOT / 'scripts/reset_test_environment.py')
assert spec and spec.loader
reset = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reset)
PROJECT = 'ocor-bootstrap'
LABEL = 'com.docker.compose.project'
IDENTITY = 'a' * 64


class Docker:
    def __init__(self, *, kind='network', residue=False, label=PROJECT, failure=None, rename=False):
        self.kind, self.residue, self.label = kind, residue, label
        self.failure, self.rename = failure, rename
        self.down = False
        self.commands = []

    def __call__(self, command, *, cwd, timeout):
        self.commands.append(command)
        assert 0 < timeout <= 180
        if command[:2] == ['docker', 'compose']:
            self.down = True
            return subprocess.CompletedProcess(command, 0, '', 'Resource is still in use' if self.residue else '')
        kind = command[1]
        present = kind == self.kind and (not self.down or self.residue)
        name = PROJECT + '_fixture' if kind != 'container' else PROJECT + '-fixture-1'
        if self.rename and self.down:
            name = 'renamed-resource'
        if 'ls' in command:
            if self.failure == 'list':
                return subprocess.CompletedProcess(command, 1, '', 'daemon unavailable')
            output = json.dumps({'ID': IDENTITY, 'Names': name, 'Name': name, 'Labels': f'{LABEL}={self.label}'}) + '\n'
            return subprocess.CompletedProcess(command, 0, output if present else '', '')
        assert 'inspect' in command
        if self.failure == 'inspect':
            return subprocess.CompletedProcess(command, 1, '', 'unavailable')
        if self.failure == 'malformed':
            return subprocess.CompletedProcess(command, 0, '{}', '')
        labels = {LABEL: self.label} if self.label is not None else {}
        data = {'Id': IDENTITY, 'Name': name, 'Labels': labels, 'Config': {'Labels': labels}}
        return subprocess.CompletedProcess(command, 0, json.dumps([data]), '')


def invoke(monkeypatch, capsys, fake, *args):
    monkeypatch.setattr(reset, 'run', fake)
    monkeypatch.setattr(reset, 'root', lambda: ROOT)
    monkeypatch.setattr(sys, 'argv', ['reset_test_environment.py', *args])
    result = reset.main()
    return result, json.loads(capsys.readouterr().out)


@pytest.mark.parametrize('kind,key', [('container','containers'), ('network','networks'), ('volume','volumes')])
def test_zero_compose_exit_with_owned_residue_is_failure(monkeypatch, capsys, kind, key):
    fake = Docker(kind=kind, residue=True)
    code, data = invoke(monkeypatch, capsys, fake, '--execute')
    assert code != 0, 'compose exit zero cannot prove teardown completion'
    assert data['status'] == 'FAIL'
    assert data['compose_exit_code'] == 0
    assert data['owned_resources_remaining'][key]
    assert data['owned_resources_remaining'][key][0]['name'].startswith(PROJECT)
    assert all(c[:2] in (['docker','compose'], ['docker',kind]) or c[2] == 'ls' for c in fake.commands)


@pytest.mark.parametrize('kind', ['container', 'network', 'volume'])
def test_proved_removal_and_already_absent_pass(monkeypatch, capsys, kind):
    fake = Docker(kind=kind)
    code, data = invoke(monkeypatch, capsys, fake, '--execute')
    assert code == 0 and data['status'] == 'PASS'
    assert data['owned_resources_remaining'] == {'containers': [], 'networks': [], 'volumes': []}
    code, data = invoke(monkeypatch, capsys, fake, '--execute')
    assert code == 0 and data['status'] == 'PASS'


@pytest.mark.parametrize('failure', ['list', 'inspect', 'malformed'])
def test_inventory_failure_prevents_mutation(monkeypatch, capsys, failure):
    fake = Docker(failure=failure)
    code, data = invoke(monkeypatch, capsys, fake, '--execute')
    assert code != 0 and data['status'] == 'FAIL'
    assert not fake.down


@pytest.mark.parametrize('label', [None, 'other-project'])
def test_ambiguous_ownership_prevents_mutation(monkeypatch, capsys, label):
    fake = Docker(label=label)
    code, data = invoke(monkeypatch, capsys, fake, '--execute')
    assert code != 0 and data['status'] == 'FAIL'
    assert not fake.down


def test_post_inventory_failure_is_not_pass(monkeypatch, capsys):
    fake = Docker()
    def call(command, **kwargs):
        if fake.down:
            raise reset.BootstrapError('inventory deadline expired')
        return fake(command, **kwargs)
    code, data = invoke(monkeypatch, capsys, call, '--execute')
    assert code != 0 and data['status'] == 'FAIL'


def test_unrelated_resources_never_inspected_or_removed(monkeypatch, capsys):
    def call(command, **kwargs):
        if command[:2] == ['docker', 'compose']:
            return subprocess.CompletedProcess(command, 0, '', '')
        assert 'ls' in command, 'unrelated resource must not be inspected or deleted'
        return subprocess.CompletedProcess(command, 0, json.dumps({'ID':'b'*64,'Name':'open-webui','Names':'open-webui','Labels':'other=value'})+'\n', '')
    code, data = invoke(monkeypatch, capsys, call, '--execute')
    assert code == 0 and data['status'] == 'PASS'


def test_dry_run_never_contacts_docker(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError('dry-run must not invoke Docker')
    code, data = invoke(monkeypatch, capsys, forbidden)
    assert code == 0 and data['mode'] == 'DRY_RUN'


def test_renamed_and_relabelled_previous_identity_is_rejected(monkeypatch, capsys):
    fake = Docker(residue=True, rename=True)
    def call(command, **kwargs):
        if fake.down:
            fake.label = 'other-project'
        return fake(command, **kwargs)
    code, data = invoke(monkeypatch, capsys, call, '--execute')
    assert code != 0 and data['status'] == 'FAIL'


def test_compose_failure_is_failure_even_with_zero_residue(monkeypatch, capsys):
    fake = Docker()
    def call(command, **kwargs):
        result = fake(command, **kwargs)
        if command[:2] == ['docker', 'compose']:
            return subprocess.CompletedProcess(command, 1, '', 'down failed')
        return result
    code, data = invoke(monkeypatch, capsys, call, '--execute')
    assert code != 0 and data['compose_exit_code'] == 1
    assert data['owned_resources_remaining'] == {'containers': [], 'networks': [], 'volumes': []}


@pytest.mark.parametrize('body', ['null', '[]', '{', '{}', '{"Name":"ocor-bootstrap_x"}'])
def test_malformed_list_blocks_before_down(monkeypatch, capsys, body):
    commands = []
    def call(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, body + '\n', '')
    code, data = invoke(monkeypatch, capsys, call, '--execute')
    assert code != 0 and data['status'] == 'FAIL'
    assert not any(c[:2] == ['docker','compose'] for c in commands)


def test_inventory_timeout_blocks_before_down(monkeypatch, capsys):
    fake = Docker()
    instants = iter([0, 31])
    monkeypatch.setattr(reset.time, 'monotonic', lambda: next(instants))
    code, data = invoke(monkeypatch, capsys, fake, '--execute')
    assert code != 0 and data['status'] == 'FAIL' and not fake.down


def test_inspected_uuid_substitution_blocks_before_down(monkeypatch, capsys):
    fake = Docker()
    def call(command, **kwargs):
        result = fake(command, **kwargs)
        if 'inspect' in command:
            body = json.loads(result.stdout)
            body[0]['Id'] = 'c' * 64
            result.stdout = json.dumps(body)
        return result
    code, data = invoke(monkeypatch, capsys, call, '--execute')
    assert code != 0 and data['status'] == 'FAIL' and not fake.down
