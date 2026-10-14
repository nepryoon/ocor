"""Criteri di acquisizione Fuseki del change set CI, senza ridurre i gate."""
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ("ocor-rccad.yml", "ocor-delivery-activation.yml", "ocor-validation-closure.yml")
CACHE_SHA = "0057852bfaa89a56745cba8c7296529d2fc39830"


def test_dockerfile_consumes_local_archive_and_keeps_digest_check():
    text = (ROOT / "infra/fuseki/Dockerfile").read_text()
    assert "COPY apache-jena-fuseki.tar.gz /tmp/apache-jena-fuseki.tar.gz" in text
    assert "ADD " not in text
    assert "sha512sum -c -" in text


@pytest.mark.parametrize("name", WORKFLOWS)
def test_every_full_stack_job_restores_exact_key_before_verified_build(name):
    workflow = yaml.safe_load((ROOT / ".github/workflows" / name).read_text())
    builds = 0
    for job in workflow["jobs"].values():
        steps = job["steps"]
        matching = [s for s in steps if "bootstrap_ci_environment.py --execute" in s.get("run", "")]
        if not matching:
            continue
        assert len(matching) == 1
        builds += 1
        build = matching[0]
        assert "bootstrap_ci_environment.py --execute --timeout 600" in build["run"]
        restore = next(s for s in steps if s.get("id") == "fuseki-cache")
        save = next(s for s in steps if s.get("uses", "").startswith("actions/cache/save@"))
        assert restore["uses"] == "actions/cache/restore@" + CACHE_SHA
        assert save["uses"] == "actions/cache/save@" + CACHE_SHA
        assert restore["with"] == save["with"] == {
            "key": "${{ steps.fuseki-key.outputs.key }}", "path": "${{ steps.fuseki-key.outputs.path }}"}
        assert "restore-keys" not in restore["with"]
        assert steps.index(restore) < steps.index(build) < steps.index(save)
    assert builds == (3 if name == "ocor-validation-closure.yml" else 2)


def test_build_flag_without_execute_remains_read_only(tmp_path, monkeypatch, capsys):
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import acquire_fuseki_archive as acquisition
    monkeypatch.setattr(sys, "argv", ["acquire_fuseki_archive.py", "--build-ci-image"])
    monkeypatch.setattr(acquisition, "root", lambda: tmp_path)
    monkeypatch.setattr(acquisition, "cache_info", lambda *args: {"sha512": "pinned"})
    monkeypatch.setattr(acquisition, "build_ci_image", lambda *a, **kw: pytest.fail("dry run mutated"))
    assert acquisition.main() == 0
    assert 'CHECK_ONLY' in capsys.readouterr().out
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("exit_code", [0, 1])
def test_ci_build_checks_archive_and_removes_context(tmp_path, monkeypatch, exit_code):
    import sys
    import hashlib
    import json
    import subprocess
    sys.path.insert(0, str(ROOT / "scripts"))
    import acquire_fuseki_archive as acquisition
    from ocor_bootstrap_lib import BootstrapError
    (tmp_path / "infra/fuseki").mkdir(parents=True)
    data = b"verified archive"
    digest = hashlib.sha512(data).hexdigest()
    (tmp_path / "infra/services.lock.json").write_text(json.dumps({"services": [{
        "id": "fuseki", "version": "6.2.0", "source": acquisition.SOURCES[-1],
        "build": {"source_sha512": digest}}]}))
    (tmp_path / "infra/fuseki/Dockerfile").write_text("COPY apache-jena-fuseki.tar.gz /tmp/archive\n")
    cache = tmp_path / acquisition.cache_info(tmp_path)["path"]
    cache.mkdir(parents=True)
    (cache / "apache-jena-fuseki.tar.gz").write_bytes(data)
    calls = []
    def docker(command, *, cwd, timeout):
        context = Path(command[-1])
        assert (context / "apache-jena-fuseki.tar.gz").read_bytes() == data
        assert cwd == tmp_path and 0 < timeout <= 10
        calls.append(context)
        return subprocess.CompletedProcess(command, exit_code, "", "deterministic local build fault")
    monkeypatch.setattr(acquisition, "run", docker)
    if exit_code:
        with pytest.raises(BootstrapError, match="build failed"):
            acquisition.build_ci_image(tmp_path, timeout=10)
    else:
        assert acquisition.build_ci_image(tmp_path, timeout=10)["status"] == "PASS"
    assert len(calls) == 1 and not calls[0].exists()
    (cache / "apache-jena-fuseki.tar.gz").write_bytes(b"tampered")
    with pytest.raises(BootstrapError, match="SHA512"):
        acquisition.build_ci_image(tmp_path, timeout=10)
    assert len(calls) == 1


def test_ci_build_deadline_cannot_start_docker_after_acquisition(tmp_path, monkeypatch):
    import sys
    from contextlib import contextmanager
    sys.path.insert(0, str(ROOT / "scripts"))
    import acquire_fuseki_archive as acquisition
    from ocor_bootstrap_lib import BootstrapError
    ticks = iter([0, 601])
    monkeypatch.setattr(acquisition.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(acquisition, "acquire", lambda *a, **kw: (tmp_path, {}))
    @contextmanager
    def context(*args):
        yield tmp_path
    monkeypatch.setattr(acquisition, "build_context", context)
    monkeypatch.setattr(acquisition, "run", lambda *a, **kw: pytest.fail("expired build budget"))
    with pytest.raises(BootstrapError, match="budget"):
        acquisition.build_ci_image(tmp_path)
