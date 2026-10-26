# SeaweedFS provisioning qualification

`qualify.py` validates the non-production SeaweedFS service of the `ocor-bootstrap`
stack (OCOR-DEV-REM-0038, BA-06 candidate component of ADD v1.3 Part I §2.6) against
`infra/services.lock.json`. SeaweedFS runs in single-node `mini` mode on disposable
tmpfs; only the S3 gateway is published, on `127.0.0.1:18333`. The S3 admin identity
is the generated disposable secret `OCOR_LOCAL_SEAWEEDFS_PASSWORD`, read from the
container configuration and never printed.

It fails closed unless the image is the exact locked digest, the container is healthy
and publishes only the S3 port on loopback, `/healthz` answers, unsigned and
wrong-secret requests are denied, a SigV4-signed ListBuckets succeeds and the binary
reports the exact locked version.

With `--execute` it also runs the Object Lock probe: a uniquely named bucket is created
with Object Lock (versioning is then enabled), one object is written under
`COMPLIANCE` retention, and deleting that version must be denied both plainly and with
the governance-bypass header; the version must remain readable. `COMPLIANCE` is the
mode used because no request, bypass header included, may shorten or remove it. The
probe never deletes the locked version or bucket; teardown releases the tmpfs.

```bash
python3 deploy/bootstrap/services/seaweedfs/qualify.py --execute
python3 deploy/bootstrap/services/seaweedfs/qualify.py --fault-recovery --execute
python3 deploy/bootstrap/services/seaweedfs/test_qualify.py
```

The fault/recovery campaign pauses the container, requires bounded unavailability,
always unpauses, then verifies unpause and restart recovery. A restart discards the
tmpfs contents by design. Ownership is WS-12 Infrastructure and Operations.
