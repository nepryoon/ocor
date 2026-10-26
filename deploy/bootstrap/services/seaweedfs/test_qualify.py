#!/usr/bin/env python3
"""Unit contract tests for the SeaweedFS provisioning qualification harness."""

from __future__ import annotations

import importlib.util
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


MODULE_PATH = Path(__file__).with_name("qualify.py")
SPEC = importlib.util.spec_from_file_location("seaweedfs_qualify", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {MODULE_PATH}")
qualify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qualify)

IMAGE = "chrislusf/seaweedfs@sha256:" + "a" * 64


def lock(**overrides: Any) -> dict[str, Any]:
    entry = {
        "id": "seaweedfs",
        "image": IMAGE,
        "version": "4.51",
        "official_source": True,
        "source": "https://hub.docker.com/r/chrislusf/seaweedfs",
        "license": "Apache-2.0",
    }
    entry.update(overrides)
    return {"services": [entry]}


def inspection(**ports: Any) -> dict[str, Any]:
    return {
        "Config": {"Image": IMAGE, "Env": ["AWS_ACCESS_KEY_ID=ocor-bootstrap-s3", "AWS_SECRET_ACCESS_KEY=" + "s" * 43]},
        "State": {"Running": True, "Health": {"Status": "healthy"}},
        "NetworkSettings": {"Ports": ports or {"8333/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18333"}]}},
    }


def observations(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "health_status": 200,
        "unsigned_status": 403,
        "unsigned_body": "<Error><Code>AccessDenied</Code></Error>",
        "wrong_secret_status": 403,
        "signed_status": 200,
        "version_output": "version 30GB 4.51 ffa87c25f linux amd64",
        "expected_version": "4.51",
    }
    values.update(overrides)
    return values


def lock_observed(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "create_status": 200,
        "create_code": "",
        "versioning_body": "<VersioningConfiguration><Status>Enabled</Status></VersioningConfiguration>",
        "lock_body": "<ObjectLockConfiguration><ObjectLockEnabled>Enabled</ObjectLockEnabled></ObjectLockConfiguration>",
        "put_status": 200,
        "version_id": "v1",
        "retention_body": "<Retention><Mode>COMPLIANCE</Mode></Retention>",
        "delete_status": 403,
        "bypass_delete_status": 403,
        "read_status": 200,
        "read_body": "payload",
        "payload": "payload",
    }
    values.update(overrides)
    return values


class SeaweedFSQualificationContractTests(unittest.TestCase):
    def test_lock_contract_accepts_exact_digest_and_version(self) -> None:
        self.assertEqual(qualify.validate_lock(lock())["version"], "4.51")

    def test_lock_contract_rejects_mutable_image(self) -> None:
        with self.assertRaisesRegex(qualify.QualificationError, "digest-pinned"):
            qualify.validate_lock(lock(image="chrislusf/seaweedfs:4.51"))

    def test_lock_contract_rejects_license_and_source_drift(self) -> None:
        with self.assertRaisesRegex(qualify.QualificationError, "license"):
            qualify.validate_lock(lock(license="AGPL-3.0"))
        with self.assertRaisesRegex(qualify.QualificationError, "source"):
            qualify.validate_lock(lock(source="https://example.invalid/seaweedfs"))

    def test_runtime_contract_accepts_loopback_s3_only(self) -> None:
        self.assertEqual(qualify.validate_inspection(inspection(), IMAGE)["ports"], {"8333/tcp": "18333"})

    def test_runtime_contract_rejects_external_binding(self) -> None:
        with self.assertRaisesRegex(qualify.QualificationError, "loopback-only"):
            qualify.validate_inspection(
                inspection(**{"8333/tcp": [{"HostIp": "0.0.0.0", "HostPort": "18333"}]}), IMAGE
            )

    def test_runtime_contract_rejects_extra_publication(self) -> None:
        extra = {
            "8333/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18333"}],
            "8888/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8888"}],
        }
        with self.assertRaisesRegex(qualify.QualificationError, "exactly the S3 gateway"):
            qualify.validate_inspection(inspection(**extra), IMAGE)

    def test_runtime_contract_rejects_unhealthy_or_other_image(self) -> None:
        unhealthy = inspection()
        unhealthy["State"]["Health"]["Status"] = "starting"
        with self.assertRaisesRegex(qualify.QualificationError, "not healthy"):
            qualify.validate_inspection(unhealthy, IMAGE)
        with self.assertRaisesRegex(qualify.QualificationError, "differs"):
            qualify.validate_inspection(inspection(), "chrislusf/seaweedfs@sha256:" + "b" * 64)

    def test_credentials_require_a_generated_secret(self) -> None:
        self.assertEqual(qualify.credentials(inspection())[0], "ocor-bootstrap-s3")
        weak = inspection()
        weak["Config"]["Env"] = ["AWS_ACCESS_KEY_ID=x", "AWS_SECRET_ACCESS_KEY=short"]
        with self.assertRaisesRegex(qualify.QualificationError, "credentials"):
            qualify.credentials(weak)

    def test_sigv4_matches_the_published_aws_example(self) -> None:
        # AWS S3 API reference, "Signature Calculations for the Authorization
        # Header", example GET Object request. The access key id is not part
        # of the string to sign, so the published signature holds for any id;
        # a neutral id replaces the documented AKIA-shaped one, which the
        # supply-chain secret scanner rightly refuses in the repository.
        headers = qualify.sign(
            "GET",
            "https://examplebucket.s3.amazonaws.com/test.txt",
            "OCOR-SIGV4-EXAMPLE-KEY-ID",
            "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            now=datetime(2013, 5, 24, tzinfo=UTC),
            headers={"Range": "bytes=0-9"},
        )
        self.assertEqual(
            headers["authorization"],
            "AWS4-HMAC-SHA256 Credential=OCOR-SIGV4-EXAMPLE-KEY-ID/20130524/us-east-1/s3/aws4_request, "
            "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date, "
            "Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41",
        )

    def test_observations_accept_the_fail_closed_profile(self) -> None:
        result = qualify.validate_observations(**observations())
        self.assertEqual(result["unsigned_access"], "FAIL_CLOSED")
        self.assertEqual(result["wrong_secret_access"], "FAIL_CLOSED")

    def test_observations_reject_open_or_degraded_service(self) -> None:
        cases = {
            "health endpoint": {"health_status": 503},
            "unsigned": {"unsigned_status": 200, "unsigned_body": "<ListAllMyBucketsResult/>"},
            "wrong secret": {"wrong_secret_status": 200},
            "signed": {"signed_status": 403},
            "version": {"version_output": "version 30GB 4.510 x"},
        }
        for message, override in cases.items():
            with self.subTest(message=message), self.assertRaisesRegex(qualify.QualificationError, message):
                qualify.validate_observations(**observations(**override))

    def test_object_lock_accepts_denied_deletes_and_intact_version(self) -> None:
        result = qualify.validate_object_lock(lock_observed())
        self.assertEqual(result["retained_version_delete"], "FAIL_CLOSED")
        self.assertTrue(result["retained_version_intact"])
        reused = qualify.validate_object_lock(lock_observed(create_status=409, create_code="BucketAlreadyOwnedByYou"))
        self.assertEqual(reused["bucket_object_lock"], "Enabled")

    def test_object_lock_rejects_every_weakened_branch(self) -> None:
        cases = {
            "bucket creation": {"create_status": 409, "create_code": "BucketAlreadyExists"},
            "versioning": {"versioning_body": "<VersioningConfiguration/>"},
            "Object Lock configuration": {"lock_body": "<Error/>"},
            "no version": {"version_id": ""},
            "retention mode": {"retention_body": "<Retention><Mode>GOVERNANCE</Mode></Retention>"},
            "deleting a retained": {"delete_status": 204},
            "governance bypass": {"bypass_delete_status": 204},
            "not intact": {"read_status": 404},
        }
        for message, override in cases.items():
            with self.subTest(message=message), self.assertRaisesRegex(qualify.QualificationError, message):
                qualify.validate_object_lock(lock_observed(**override))

    def test_fault_recovery_requires_explicit_execute(self) -> None:
        with self.assertRaisesRegex(qualify.QualificationError, "requires explicit --execute"):
            qualify.qualify(qualify.parse_args(["--fault-recovery", "--lock", "/nonexistent/lock.json"]))


if __name__ == "__main__":
    unittest.main()
