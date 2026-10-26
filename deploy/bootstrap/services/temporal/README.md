# Temporal provisioning qualification

`qualify.py` validates the non-production Temporal service of the `ocor-bootstrap`
stack (OCOR-DEV-REM-0038, BA-05 candidate component of ADD v1.3 Part I §2.6) against
`infra/services.lock.json`. Three containers are checked: the server
(`temporalio/server`), its own PostgreSQL (the locked `postgres` image, never published
on the host) and admin-tools (`temporalio/admin-tools`), which applies the pinned
PostgreSQL schema before the server starts and carries the official `temporal` CLI.

It fails closed unless every image is the exact locked digest, the containers are
healthy, the frontend is published only on `127.0.0.1:17233`, PostgreSQL and
admin-tools publish nothing, the cluster reports `SERVING` with the exact locked server
version, and describing an absent namespace fails. Because the frontend speaks gRPC
only, protocol probes run the pinned CLI inside admin-tools on the project network.

The mutating fault/recovery campaign requires both flags:

```bash
python3 deploy/bootstrap/services/temporal/qualify.py --fault-recovery --execute
```

It pauses the server, requires bounded unavailability, always unpauses in a `finally`
block, then verifies unpause and restart recovery. Commands use argument vectors with
finite timeouts and emit versioned JSON without environment variables or credentials.
The service is disposable; ownership is WS-12 Infrastructure and Operations.

```bash
python3 deploy/bootstrap/services/temporal/test_qualify.py
```
