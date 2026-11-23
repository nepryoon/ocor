"""Positive and fail-closed acquisition checks under the PO archive decision."""
from __future__ import annotations

import hashlib
import io
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import acquire_fuseki_archive as archive
from ocor_bootstrap_lib import BootstrapError

# CI-FUSEKI-ARCHIVE-TIMEOUT-20261123 point 1. Literal, so the RED run does not
# depend on a constant the production module does not have yet.
GOVERNED_COPY = (
    "https://github.com/nepryoon/ocor/releases/download/"
    "mirror-apache-jena-fuseki-6.2.0/apache-jena-fuseki-6.2.0.tar.gz"
)
RELEASE_ASSET = "https://release-assets.githubusercontent.com/github-production-release-asset/ok"
DLCDN = "https://dlcdn.apache.org/jena/binaries/apache-jena-fuseki-6.2.0.tar.gz"
ARCHIVE = "https://archive.apache.org/dist/jena/binaries/apache-jena-fuseki-6.2.0.tar.gz"


def repository(tmp_path, data=b"governed archive"):
    (tmp_path / "infra").mkdir()
    service = {"id": "fuseki", "version": "6.2.0", "source": archive.SOURCES[-1],
               "build": {"source_sha512": hashlib.sha512(data).hexdigest()}}
    (tmp_path / "infra/services.lock.json").write_text(json.dumps({"services": [service]}))
    return tmp_path


class Response(io.BytesIO):
    def geturl(self):
        return archive.SOURCES[0]


def opener(data, calls):
    def fetch(request, timeout):
        calls.append((request.full_url, timeout))
        return Response(data)
    return fetch


def test_verified_miss_then_hit_rechecks_bytes(tmp_path, monkeypatch):
    repo = repository(tmp_path)
    calls = []
    monkeypatch.setattr(archive, "urlopen", opener(b"governed archive", calls))
    path, miss = archive.acquire(repo, timeout=10)
    assert path.read_bytes() == b"governed archive"
    assert miss["cache"] == "MISS" and miss["source"] == archive.SOURCES[0]
    assert miss["verified_sha512"] == hashlib.sha512(path.read_bytes()).hexdigest()
    same, hit = archive.acquire(repo, timeout=10)
    assert same == path and hit["cache"] == "HIT"
    assert hit["source"] == miss["source"] and len(calls) == 1
    path.write_bytes(b"corrupt")
    with pytest.raises(BootstrapError, match="SHA512"):
        archive.acquire(repo, timeout=10)
    assert len(calls) == 1


def test_official_fallback_order_and_no_extra_retry(tmp_path, monkeypatch):
    repo = repository(tmp_path)
    calls = []
    def fetch(request, timeout):
        calls.append(request.full_url)
        if len(calls) < 3:
            raise URLError("unavailable")
        return Response(b"governed archive")
    monkeypatch.setattr(archive, "urlopen", fetch)
    path, result = archive.acquire(repo, timeout=10)
    assert calls == list(archive.SOURCES)
    assert path.is_file() and result["source"] == archive.SOURCES[-1]


def test_all_sources_unavailable_fail_closed_without_partial_cache(tmp_path, monkeypatch):
    repo = repository(tmp_path)
    calls = []
    def fetch(request, timeout):
        calls.append(request.full_url)
        raise URLError("unavailable")
    monkeypatch.setattr(archive, "urlopen", fetch)
    with pytest.raises(BootstrapError, match="official sources exhausted"):
        archive.acquire(repo, timeout=10)
    assert calls == list(archive.SOURCES)
    assert not list(repo.rglob("*.part")) and not list(repo.rglob("*.tar.gz"))


def test_wrong_download_digest_is_not_retried_or_cached(tmp_path, monkeypatch):
    repo = repository(tmp_path)
    calls = []
    monkeypatch.setattr(archive, "urlopen", opener(b"wrong", calls))
    with pytest.raises(BootstrapError, match="SHA512"):
        archive.acquire(repo, timeout=10)
    assert len(calls) == 1 and not list(repo.rglob("*.tar.gz"))


def test_redirect_outside_apache_is_rejected(tmp_path, monkeypatch):
    repo = repository(tmp_path)
    class Redirect(Response):
        def geturl(self):
            return "https://mirror.invalid/fuseki.tar.gz"
    monkeypatch.setattr(archive, "urlopen", lambda *a, **kw: Redirect(b"governed archive"))
    with pytest.raises(BootstrapError, match="official Apache"):
        archive.acquire(repo, timeout=10)


def test_budget_exhaustion_is_fail_closed(tmp_path, monkeypatch):
    repo = repository(tmp_path)
    ticks = iter([0, 11])
    monkeypatch.setattr(archive.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(archive, "urlopen", lambda *a, **kw: pytest.fail("expired budget"))
    with pytest.raises(BootstrapError, match="budget"):
        archive.acquire(repo, timeout=10)


@pytest.mark.parametrize("timeout", [0, -1, 601])
def test_budget_cannot_be_extended(tmp_path, timeout):
    with pytest.raises(BootstrapError, match="budget"):
        archive.acquire(repository(tmp_path), timeout=timeout)


def test_cache_symlink_cannot_write_outside_repository(tmp_path, monkeypatch):
    repo = repository(tmp_path)
    (repo / ".ocor").symlink_to(tmp_path / "infra", target_is_directory=True)
    monkeypatch.setattr(archive, "urlopen", lambda *a, **kw: pytest.fail("unsafe path"))
    with pytest.raises(BootstrapError, match="symlink"):
        archive.acquire(repo, timeout=10)


def test_cache_key_uses_only_locked_sha512(tmp_path):
    repo = repository(tmp_path)
    info = archive.cache_info(repo)
    assert info["key"] == "fuseki-sha512-" + hashlib.sha512(b"governed archive").hexdigest()
    assert info["path"].startswith(".ocor/cache/fuseki/sha512/")
    lock = repo / "infra/services.lock.json"
    damaged = json.loads(lock.read_text())
    damaged["services"][0]["build"]["source_sha512"] = "../outside"
    lock.write_text(json.dumps(damaged))
    with pytest.raises(BootstrapError):
        archive.cache_info(repo)


def test_verified_copy_is_rechecked_and_context_is_removed(tmp_path, monkeypatch):
    repo = repository(tmp_path)
    (repo / 'infra/fuseki').mkdir()
    (repo / 'infra/fuseki/Dockerfile').write_text('COPY apache-jena-fuseki.tar.gz /tmp/archive\n')
    monkeypatch.setattr(archive, 'urlopen', opener(b'governed archive', []))
    path, _ = archive.acquire(repo, timeout=10)
    with archive.build_context(repo, path) as context:
        assert (context / 'apache-jena-fuseki.tar.gz').read_bytes() == path.read_bytes()
        assert (context / 'Dockerfile').read_text().startswith('COPY')
    assert not context.exists()
    path.write_bytes(b'changed after acquisition')
    with pytest.raises(BootstrapError, match='SHA512'):
        with archive.build_context(repo, path):
            pytest.fail('tampered archive consumed')


def test_ci_cache_actions_are_exact_key_pinned_in_every_stack_job():
    import yaml
    repo = Path(__file__).resolve().parents[2]
    jobs = {}
    for name in ('ocor-rccad.yml', 'ocor-delivery-activation.yml', 'ocor-validation-closure.yml'):
        workflow = yaml.safe_load((repo / '.github/workflows' / name).read_text())
        jobs.update(workflow['jobs'])
    # Every job that provisions the stack: each parallel part and each aggregator that still runs gates on the stack.
    provisioning_jobs = {name for name, job in jobs.items()
                         if any(s.get('name') == 'Provision the full pinned disposable stack' for s in job['steps'])}
    assert provisioning_jobs == {
        'rccad-methodology-part', 'rccad-methodology', 'delivery-activation-part', 'delivery-activation',
        'validation-closure-part', 'validation-closure', 'conditional-infrastructure-0049-part'}
    # The 0049 aggregator only verifies the parts' union and never provisions or restores a stack.
    assert set(jobs) - provisioning_jobs == {'conditional-infrastructure-0049'}
    assert not any('cache' in s.get('uses', '') for s in jobs['conditional-infrastructure-0049']['steps'])
    for job in (jobs[name] for name in sorted(provisioning_jobs)):
        steps = job['steps']
        restore = next(s for s in steps if s.get('id') == 'fuseki-cache')
        save = next(s for s in steps if s.get('uses', '').startswith('actions/cache/save@'))
        assert restore['uses'] == 'actions/cache/restore@0057852bfaa89a56745cba8c7296529d2fc39830'
        assert save['uses'] == 'actions/cache/save@0057852bfaa89a56745cba8c7296529d2fc39830'
        assert restore['with'] == save['with'] == {
            'key': '${{ steps.fuseki-key.outputs.key }}', 'path': '${{ steps.fuseki-key.outputs.path }}'}
        assert 'restore-keys' not in restore['with']
        provisioning = next(s for s in steps if s.get('name') == 'Provision the full pinned disposable stack')
        assert steps.index(restore) < steps.index(provisioning) < steps.index(save)


def test_provisioning_total_budget_expires_before_any_docker_mutation(tmp_path, monkeypatch):
    import bootstrap_ci_environment as ci
    monkeypatch.setattr(ci, 'validate_locks', lambda repo: [])
    ticks = iter([0, 601])
    monkeypatch.setattr(ci.time, 'monotonic', lambda: next(ticks))
    monkeypatch.setattr(ci, 'execute', lambda *args: pytest.fail('expired provisioning'))
    with pytest.raises(BootstrapError, match='total provisioning budget'):
        ci.provision(tmp_path, 600)


def test_miss_rejects_provenance_symlink_before_download(tmp_path, monkeypatch):
    repo = repository(tmp_path)
    directory = repo / archive.cache_info(repo)['path']
    directory.mkdir(parents=True)
    victim = repo / 'infra/services.lock.json'
    before = victim.read_bytes()
    (directory / 'provenance.json').symlink_to(victim)
    monkeypatch.setattr(archive, 'urlopen', lambda *a, **kw: pytest.fail('unsafe provenance'))
    with pytest.raises(BootstrapError, match='symlink'):
        archive.acquire(repo, timeout=10)
    assert victim.read_bytes() == before


def test_redirect_guard_checks_before_following_third_party():
    from urllib.request import Request
    guard = archive.OfficialRedirect()
    with pytest.raises(BootstrapError, match='official Apache'):
        guard.redirect_request(Request(archive.SOURCES[0]), None, 302, 'Found', {}, 'https://mirror.invalid/file')


def test_stream_deadline_falls_back_then_total_budget_rejects(tmp_path, monkeypatch):
    repo = repository(tmp_path)
    # First source connects but stalls; no fresh global budget is allocated.
    ticks = iter([0, 0, 0, 0, 121, 121, 121, 121, 121, 121, 121])
    monkeypatch.setattr(archive.time, 'monotonic', lambda: next(ticks))
    calls = []
    monkeypatch.setattr(archive, 'urlopen', opener(b'governed archive', calls))
    with pytest.raises(BootstrapError, match='budget'):
        archive.acquire(repo, timeout=120)
    assert len(calls) == 1 and not list(repo.rglob('*.part'))


def test_stream_reads_one_receive_and_refreshes_transport_deadline(tmp_path, monkeypatch):
    from types import SimpleNamespace
    repo = repository(tmp_path)
    timeouts = []
    class Stream(Response):
        fp = SimpleNamespace(raw=SimpleNamespace(_sock=SimpleNamespace(settimeout=timeouts.append)))
        def read(self, *args):
            pytest.fail('read(size) can wait through indefinitely dribbling chunks')
        def read1(self, size):
            return io.BytesIO.read(self, size)
    monkeypatch.setattr(archive, 'urlopen', lambda *a, **kw: Stream(b'governed archive'))
    path, _ = archive.acquire(repo, timeout=10)
    assert path.is_file() and timeouts and all(0 < value <= 10 for value in timeouts)


def _body(data, url):
    class Body(Response):
        def geturl(self):
            return url

    return Body(data)


def test_governed_copy_is_the_only_download_when_bytes_match(tmp_path, monkeypatch):
    repo = repository(tmp_path)
    calls = []

    def fetch(request, timeout):
        calls.append(request.full_url)
        return _body(b"governed archive", RELEASE_ASSET)

    monkeypatch.setattr(archive, "urlopen", fetch)
    path, result = archive.acquire(repo, timeout=10)
    assert calls == [GOVERNED_COPY]
    assert result["cache"] == "MISS" and result["source"] == GOVERNED_COPY
    assert path.read_bytes() == b"governed archive"
    assert result["verified_sha512"] == hashlib.sha512(b"governed archive").hexdigest()


def test_governed_copy_digest_mismatch_names_the_copy_and_stops(tmp_path, monkeypatch):
    repo = repository(tmp_path)
    calls = []

    def fetch(request, timeout):
        calls.append(request.full_url)
        return _body(b"not the locked bytes", request.full_url)

    monkeypatch.setattr(archive, "urlopen", fetch)
    with pytest.raises(BootstrapError, match="SHA512") as caught:
        archive.acquire(repo, timeout=10)
    assert GOVERNED_COPY in str(caught.value)
    assert calls == [GOVERNED_COPY]
    assert not list(repo.rglob("*.tar.gz"))
    assert not list(repo.rglob("*.part"))
    assert not list(repo.rglob("provenance.json"))


def test_copy_redirects_only_to_https_release_assets():
    from urllib.request import Request

    guard = archive.OfficialRedirect()
    allowed = guard.redirect_request(
        Request(GOVERNED_COPY), None, 302, "Found", {}, RELEASE_ASSET,
    )
    assert urlparse(allowed.get_full_url()).hostname == "release-assets.githubusercontent.com"
    rejected = (
        "http://release-assets.githubusercontent.com/asset",
        "https://example.invalid/asset",
        GOVERNED_COPY,
        "https://release-assets.githubusercontent.com.evil/asset",
        "https://user@release-assets.githubusercontent.com/asset",
        "https://release-assets.githubusercontent.com:444/asset",
    )
    for target in rejected:
        with pytest.raises(BootstrapError, match="official Apache"):
            guard.redirect_request(Request(GOVERNED_COPY), None, 302, "Found", {}, target)
    with pytest.raises(BootstrapError, match="official Apache"):
        guard.redirect_request(Request(DLCDN), None, 302, "Found", {}, RELEASE_ASSET)
    apache = guard.redirect_request(Request(DLCDN), None, 302, "Found", {}, ARCHIVE)
    assert urlparse(apache.get_full_url()).hostname == "archive.apache.org"


@pytest.mark.parametrize("final", [
    "http://release-assets.githubusercontent.com/asset",
    "https://example.invalid/asset",
])
def test_copy_final_url_outside_release_assets_is_rejected(tmp_path, monkeypatch, final):
    repo = repository(tmp_path)
    calls = []

    def fetch(request, timeout):
        calls.append(request.full_url)
        return _body(b"governed archive", final)

    monkeypatch.setattr(archive, "urlopen", fetch)
    with pytest.raises(BootstrapError, match="official Apache"):
        archive.acquire(repo, timeout=10)
    assert calls == [GOVERNED_COPY]
    assert not list(repo.rglob("*.tar.gz"))


def test_copy_http_404_falls_through_to_apache_sources(tmp_path, monkeypatch):
    repo = repository(tmp_path)
    calls = []

    def fetch(request, timeout):
        calls.append(request.full_url)
        if request.full_url == GOVERNED_COPY:
            raise HTTPError(GOVERNED_COPY, 404, "Not Found", hdrs=None, fp=None)
        return _body(b"governed archive", request.full_url)

    monkeypatch.setattr(archive, "urlopen", fetch)
    path, result = archive.acquire(repo, timeout=10)
    assert calls[0] == GOVERNED_COPY
    assert DLCDN in calls
    assert result["source"] == DLCDN
    assert path.read_bytes() == b"governed archive"
    assert calls.count(GOVERNED_COPY) == 1


def test_copy_source_deadline_falls_through_to_apache_sources(tmp_path, monkeypatch):
    repo = repository(tmp_path)
    clock = {"t": 0.0}
    monkeypatch.setattr(archive.time, "monotonic", lambda: clock["t"])
    calls = []

    class Stall(Response):
        def geturl(self):
            return GOVERNED_COPY

        def read1(self, size):
            clock["t"] = 121.0
            return b"x"

    def fetch(request, timeout):
        calls.append(request.full_url)
        if request.full_url == GOVERNED_COPY:
            return Stall(b"partial")
        return _body(b"governed archive", request.full_url)

    monkeypatch.setattr(archive, "urlopen", fetch)
    path, result = archive.acquire(repo, timeout=300)
    assert calls[0] == GOVERNED_COPY
    assert result["source"] == DLCDN
    assert path.read_bytes() == b"governed archive"
    assert not list(repo.rglob("*.part"))


def test_governed_copy_request_sends_no_authorization_header(tmp_path, monkeypatch):
    repo = repository(tmp_path)
    seen = []

    def fetch(request, timeout):
        seen.append(request)
        return _body(b"governed archive", GOVERNED_COPY)

    monkeypatch.setattr(archive, "urlopen", fetch)
    _path, result = archive.acquire(repo, timeout=10)
    assert result["source"] == GOVERNED_COPY
    assert len(seen) == 1 and seen[0].full_url == GOVERNED_COPY
    names = [name.lower() for name, _value in seen[0].header_items()]
    assert "authorization" not in names
    assert "token" not in seen[0].full_url
