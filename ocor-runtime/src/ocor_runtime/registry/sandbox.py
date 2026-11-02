"""Sandboxed execution of Function and Model artefacts (NFR-025, Register v1.1 :182).

The execution of a Function applies a sandbox, a timeout and configurable quotas of CPU,
memory and output size; every overrun ends fail-safe (the process group is killed and no
output is returned) and is reported as a ``SandboxOverrun`` that the registry audits.

Profile ``SANDBOX_PROFILE``: the artefact is Python source run by a fresh isolated
interpreter (``-I -S``, empty environment, empty temporary working directory, new
session, no inherited descriptors) under ``RLIMIT_CPU``, ``RLIMIT_AS``,
``RLIMIT_FSIZE=0``, ``RLIMIT_CORE=0`` and ``RLIMIT_NPROC=0`` (no fork). After reading
its request the runner lowers ``RLIMIT_NOFILE`` to the three standard descriptors, so
the artefact cannot open a file or a socket; as defence in depth its builtins have no
``open``, ``exec``, ``eval`` or ``compile`` and import only ``json`` and ``math``. The wall-clock timeout, the
CPU time actually consumed (``wait4`` resource usage) and the canonical output size
are enforced by the parent. Artefact bytes are checked against their pinned digest
before execution.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import resource
import select
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..kernel.canonical import canonical_bytes, parse_i_json
from .contract import RegistryError, ResourceBudget

SANDBOX_PROFILE = "urn:ocor:registry:sandbox:python-rlimit:1"
OVERRUN_KINDS = ("TIMEOUT", "CPU", "MEMORY", "OUTPUT")
_STREAM_SLACK = 4096

# The runner: reads one JSON request from stdin, closes the descriptor budget, executes
# the artefact source and writes one JSON response to stdout.
_RUNNER = r"""
import json, math, resource, sys
request = json.loads(sys.stdin.buffer.read())
sys.stdin.close()
resource.setrlimit(resource.RLIMIT_NOFILE, (3, 3))
def respond(value):
    sys.stdout.write(json.dumps(value, sort_keys=True, separators=(",", ":")))
    sys.stdout.flush()
import builtins
ALLOWED = {"json": json, "math": math}
def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level or name not in ALLOWED:
        raise ImportError("import is not available in the sandbox")
    return ALLOWED[name]
safe = {k: v for k, v in vars(builtins).items()
        if k not in ("open", "exec", "eval", "compile", "input", "breakpoint", "help", "exit", "quit",
                     "__import__", "__loader__", "__spec__")}
safe["__import__"] = guarded_import
try:
    scope = {"__builtins__": safe, "json": json, "math": math}
    exec(compile(request["source"], "<artefact>", "exec"), scope)
    output = scope[request["entrypoint"]](*request["arguments"])
    respond({"status": "OK", "output": output})
except MemoryError:
    respond({"status": "MEMORY"})
except BaseException as exc:
    respond({"status": "FAILED", "error": type(exc).__name__})
"""


class SandboxOverrun(Exception):
    """A budget overrun: the run was terminated fail-safe and returned no output."""

    def __init__(self, kind: str, detail: str) -> None:
        if kind not in OVERRUN_KINDS:
            raise ValueError(f"undeclared overrun kind: {kind!r}")
        self.kind = kind
        self.detail = detail
        super().__init__(f"{kind}: {detail}")


@dataclass(frozen=True, slots=True)
class SandboxRun:
    output: Any
    cpu_millis: int
    output_bytes: int


def _limits(budget: ResourceBudget) -> Callable[[], None]:
    cpu_seconds = max(1, math.ceil(budget.cpu_millis / 1000))

    def apply() -> None:
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
        resource.setrlimit(resource.RLIMIT_AS, (budget.memory_bytes, budget.memory_bytes))
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))

    return apply


def _kill(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return


class PythonSandbox:
    """Runs an artefact entrypoint under a ``ResourceBudget``; raises ``SandboxOverrun``."""

    profile = SANDBOX_PROFILE

    def run(self, *, source: bytes, artifact_digest: str, entrypoint: str, arguments: list[Any],
            budget: ResourceBudget) -> SandboxRun:
        if "urn:sha256:" + hashlib.sha256(source).hexdigest() != artifact_digest:
            raise RegistryError("CONTRACT_REJECTED", "artefact bytes do not match the pinned artifact_digest")
        try:
            text = source.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RegistryError("CONTRACT_REJECTED", "artefact source is not UTF-8") from exc
        assert budget.timeout is not None
        request = json.dumps({"source": text, "entrypoint": entrypoint, "arguments": arguments}).encode("utf-8")
        with tempfile.TemporaryDirectory(prefix="ocor-registry-sandbox-") as workdir:
            process = subprocess.Popen(  # noqa: S603 - fixed interpreter and runner, no shell
                [sys.executable, "-I", "-S", "-c", _RUNNER],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                cwd=workdir, env={}, close_fds=True, start_new_session=True, preexec_fn=_limits(budget),
            )
            return self._supervise(process, request, budget)

    def _supervise(self, process: subprocess.Popen[bytes], request: bytes, budget: ResourceBudget) -> SandboxRun:
        assert process.stdin is not None and process.stdout is not None and budget.timeout is not None
        deadline = time.monotonic() + budget.timeout.total_seconds()
        try:
            process.stdin.write(request)
            process.stdin.close()
        except BrokenPipeError:
            process.stdin = None
        cap = budget.output_bytes + _STREAM_SLACK
        received = bytearray()
        overrun: SandboxOverrun | None = None
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                overrun = SandboxOverrun("TIMEOUT", f"wall-clock timeout of {budget.timeout.total_seconds()} s")
                break
            ready, _, _ = select.select([process.stdout], [], [], remaining)
            if not ready:
                continue
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                break
            received.extend(chunk)
            if len(received) > cap:
                overrun = SandboxOverrun("OUTPUT", f"output exceeds {budget.output_bytes} bytes")
                break
        if overrun is not None:
            _kill(process)
        _, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
        process.stdout.close()
        cpu_millis = math.ceil((usage.ru_utime + usage.ru_stime) * 1000)
        if overrun is not None:
            raise overrun
        if os.WIFSIGNALED(status) and os.WTERMSIG(status) in (signal.SIGXCPU, signal.SIGKILL):
            raise SandboxOverrun("CPU", f"CPU quota of {budget.cpu_millis} ms exhausted")
        if cpu_millis > budget.cpu_millis:
            raise SandboxOverrun("CPU", f"CPU time {cpu_millis} ms exceeds the quota of {budget.cpu_millis} ms")
        try:
            response = parse_i_json(bytes(received))
        except ValueError as exc:
            raise RegistryError("EXECUTION_FAILED", "the artefact produced no valid response") from exc
        if not isinstance(response, dict):
            raise RegistryError("EXECUTION_FAILED", "the artefact produced no valid response")
        if response.get("status") == "MEMORY":
            raise SandboxOverrun("MEMORY", f"memory quota of {budget.memory_bytes} bytes exhausted")
        if response.get("status") != "OK" or set(response) != {"status", "output"}:
            raise RegistryError("EXECUTION_FAILED", f"the artefact failed: {str(response.get('error', ''))[:64]}")
        try:
            size = len(canonical_bytes(response["output"]))
        except ValueError as exc:
            raise RegistryError("EXECUTION_FAILED", "the artefact output is not I-JSON") from exc
        if size > budget.output_bytes:
            raise SandboxOverrun("OUTPUT", f"output of {size} bytes exceeds {budget.output_bytes} bytes")
        return SandboxRun(output=response["output"], cpu_millis=cpu_millis, output_bytes=size)
