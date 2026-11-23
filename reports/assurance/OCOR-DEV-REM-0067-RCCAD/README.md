# OCOR-DEV-REM-0067 — CI Fuseki label contract

Design contract for the unit required by FUSEKI-ETICHETTA-CI (2026-11-21), points 2–8, with the identifier rule of FUSEKI-ETICHETTA-CI-ORDINE (2026-11-21). This commit is that contract. It is the one design review. It does not change production behaviour.

## Identifier

The identifier is `OCOR-DEV-REM-` plus the highest four-digit `OCOR-DEV-REM-NNNN` on `origin/main` and in remote branch names (case-insensitive), plus one. Gaps are not filled.

Measured on `origin/main` `618e72c00f994e8ea8899914548cc38743aa4569`:

- `git grep -h -o -E 'OCOR-DEV-REM-[0-9]{4}' origin/main | sort -u | tail -n 1` prints `OCOR-DEV-REM-0066`.
- `git branch -r | grep -oE -i 'ocor-dev-rem-[0-9]{4}' | tr '[:lower:]' '[:upper:]' | sort -u | tail -n 1` prints `OCOR-DEV-REM-0066`.

No `OCOR-DEV-REM-0067` is present on `origin/main` or in remote branch names. The next identifier is `OCOR-DEV-REM-0067`.

## Property

After every run of the CI bootstrap on a machine, `docker image inspect ocor/jena-fuseki:6.2.0` has the same outcome as before that run: the same id, or absent if it was absent.

The CI bootstrap builds and qualifies Fuseki on its own label, distinct from `build.output_image`, and starts the CI stack on that label. `scripts/verify_external_services.py` expects the CI label only for the stack started by the CI bootstrap. The development bootstrap is unchanged. Nothing the CI leaves under `.ocor/` changes the image the development bootstrap uses.

`build.output_image` in `infra/services.lock.json` stays `ocor/jena-fuseki:6.2.0`. The CI label is the constant `ocor/jena-fuseki:ci-6.2.0`. It is distinct from `build.output_image`, from `ocor/jena-fuseki:preserve-f5a11814`, and from `ocor/jena-fuseki:ci` (the optional tag of `build_ci_image` in `scripts/acquire_fuseki_archive.py`, which this unit does not change). `infra/services.lock.json`, `infra/fuseki/local_identity.lock.json`, the Dockerfile, gates, thresholds, and claims stay unchanged. The lock id compared by the development bootstrap remains `sha256:` plus `build.output_sha256` (`f5a11814be3a91bccb54a38afc1e0bfceeb9bacd6071a3d06741aae5ff8940c1` at this base).

## Mechanism

`ci_resources()` already writes `.ocor/ci-resources.yaml` and the CI bootstrap already passes it as a second Compose file after `deploy/bootstrap/compose.yaml`. Compose replaces a scalar `image` from the later file. The overlay therefore gains `services.fuseki.image` set to `ocor/jena-fuseki:ci-6.2.0`, beside the existing `JVM_ARGS`. `deploy/bootstrap/compose.yaml` stays `image: ocor/jena-fuseki:6.2.0`. An environment variable is not used, because this overlay can carry the label.

`provision()` builds with `-t ocor/jena-fuseki:ci-6.2.0` and inspects that label. It never builds, tags, or removes `ocor/jena-fuseki:6.2.0`. The CI image id may differ from `build.output_sha256`; the CI bootstrap does not gain a new identity gate. The development bootstrap keeps its own gate: it rebuilds onto `ocor/jena-fuseki:6.2.0` with `--no-cache` only when that label is absent or its id is not the lock id, then fail-closes if the built id is still not the lock id.

The typed check gains an optional `--expected-fuseki-image`. Omitted, the expected image stays `build.output_image`. The CI bootstrap passes `--expected-fuseki-image ocor/jena-fuseki:ci-6.2.0` only on the typed-check command inside `provision()`. The flag is not read from the environment and not from `.ocor/ci-resources.yaml`. When the running `Config.Image` differs, the development path (flag omitted) keeps the current sentence `fuseki running image differs from the exact services.lock.json entry`. At this base that sentence occurs only in `scripts/verify_external_services.py`. The CI path adds a separate sentence that names `ocor/jena-fuseki:ci-6.2.0`. Status values stay `READY`, `DEGRADED`, and `NOT_PROVISIONED`.

Teardown does not `docker rmi`, `docker tag`, build, or prune either label. `ocor/jena-fuseki:preserve-f5a11814` is not created, moved, or removed by this unit.

## Consumers of the Fuseki image name

Producers that can write a Fuseki tag, at this base:

| Producer | Tag it writes | This unit |
|---|---|---|
| `scripts/bootstrap_ci_environment.py` `provision()` `docker build --pull -t` `build.output_image` | `ocor/jena-fuseki:6.2.0` | Retarget to `ocor/jena-fuseki:ci-6.2.0` |
| `scripts/bootstrap_development_environment.py` `docker build --no-cache -t`, only when the id mismatches or the label is absent | `ocor/jena-fuseki:6.2.0` | Unchanged |
| `scripts/acquire_fuseki_archive.py` `build_ci_image` (`--build-ci-image` only) | `ocor/jena-fuseki:ci` | Unchanged; not the CI bootstrap |

Readers that do not build:

- `deploy/bootstrap/compose.yaml` hardcodes `ocor/jena-fuseki:6.2.0`. Development compose and a bare `docker compose -f deploy/bootstrap/compose.yaml` do not pass the CI overlay.
- `scripts/verify_external_services.py` `check_fuseki` compares `Config.Image` with `build.output_image`. Only the CI bootstrap’s typed check will pass the CI label.
- `infra/services.lock.json` and `infra/fuseki/local_identity.lock.json` name `output_image`. Neither file changes.
- `ocor-runtime/tests/tasks/test_ocor_dev_rem_0052.py` asserts the compose image string. It stays true because the compose file stays.
- Workflows `.github/workflows/ocor-rccad.yml`, `ocor-delivery-activation.yml`, and `ocor-validation-closure.yml` call `scripts/bootstrap_ci_environment.py --execute` and `--teardown --execute`. They move the governed label today only through `provision()`.
- `scripts/run_local_lane_campaign.py` runs those two commands inside a private `dockerd` (`--data-root /var/lib/docker`), not on the workstation engine.

No other file under `scripts/`, `deploy/`, `infra/`, `.github/`, or `ocor-runtime/` executes `docker build` or `docker tag` onto `ocor/jena-fuseki:6.2.0`.

## Matrix

Seven entry points: E1 CI bootstrap `--execute`; E2 CI bootstrap `--teardown --execute`; E3 development bootstrap `--execute`; E4 `docker compose` of `deploy/bootstrap/compose.yaml` alone; E5 typed check of the CI stack (flag set); E6 typed check of the development stack (flag omitted); E7 local campaign lanes.

Twenty-four states: governed image `LOCK_ID` (the lock `output_sha256`), `OTHER_ID`, or `ABSENT` (3); CI label present or absent (2); build cache warm or cleared (2); `.ocor/ci-resources.yaml` present or absent (2). Cell count: 7 × 24 = 168. The credential guard is not an extra axis: if `.ocor/bootstrap.env` exists, E1 still fail-closes before any build, as today.

Cache warmth never selects the tag. It only affects layer reuse of a build that the entry point already performs. The residue file is overwritten by E1 and is not an input of E3, E4, or E6.

Outcome function:

- E1, every state: governed id unchanged, including absent staying absent. On success the build tag and the Fuseki container `Config.Image` are `ocor/jena-fuseki:ci-6.2.0`. A pre-existing CI label may move to the new build id. E1 does not read the residue to choose the tag.
- E2, every state: no build and no tag change of either label. The CI label stays present if it was present and absent if it was absent.
- E3, governed id already `LOCK_ID`, every other state: no Fuseki build, and compose is started from `deploy/bootstrap/compose.yaml` only. CI label and residue do not cause a rebuild and do not change the image.
- E3, governed `OTHER_ID` or `ABSENT`: unchanged mismatch path. It may build onto `ocor/jena-fuseki:6.2.0` and fail-closes unless the result is `LOCK_ID`. CI label and residue do not enter that decision.
- E4, every state: no build and no tag change. The service image is the compose file’s `ocor/jena-fuseki:6.2.0`. If that label is absent, compose does not create it.
- E5, every state: the expected image is only the CLI argument `ocor/jena-fuseki:ci-6.2.0`. Match and healthy ping: `READY`. Any other `Config.Image`: `DEGRADED` with the CI sentence. Container absent: `NOT_PROVISIONED`.
- E6, every state: the expected image is only `build.output_image`. A container on the CI label is `DEGRADED` with the existing lock sentence. Residue cannot switch E6 onto the CI label.
- E7: E2 then E1 on the lane’s private engine. The workstation labels `ocor/jena-fuseki:6.2.0` and `ocor/jena-fuseki:preserve-f5a11814` are not arguments of the lane. Inside the sandbox, E1 and E2 apply.

## Examples

Positive, producer to consumer. Producer: E1 with governed `LOCK_ID`, CI label absent, cache cleared, residue absent. Consumer: `docker image inspect ocor/jena-fuseki:6.2.0` before and after reports the same id, and `docker inspect ocor-bootstrap-fuseki-1` reports `Config.Image` `ocor/jena-fuseki:ci-6.2.0`.

Negative, producer to consumer. Producer: E6 against a running container whose `Config.Image` is `ocor/jena-fuseki:ci-6.2.0`, with `.ocor/ci-resources.yaml` present. Consumer: status `DEGRADED` and the sentence `fuseki running image differs from the exact services.lock.json entry`. The residue is not consulted.

## Oracle and proofs

The oracle is `docker image inspect` before and after, on real Docker. Mocks are only for local fault handling (a failed subprocess or a missing engine in a unit test). They are not the image-id oracle.

No proof, campaign, or command of this unit creates, moves, or removes `ocor/jena-fuseki:6.2.0` or `ocor/jena-fuseki:preserve-f5a11814` on the workstation Docker. Proofs that put a governed-labelled image at risk run in a lane sandbox, on a probe image labelled as the governed image inside that private engine.

RED comes before the production change, in a later iteration. It includes a real-Docker sandbox proof that today’s `docker build --pull -t ocor/jena-fuseki:6.2.0` moves that probe label when the cache is cleared. GREEN shows the same sandbox leaving the probe id unchanged and the CI container on `ocor/jena-fuseki:ci-6.2.0`. No existing test is removed or weakened. A changed test records the line before, the line after, and the reason.

## Later code, not this commit

Authorised production files, only after this review and only after `FUSEKI-ARCHIVE-COPY-20261123` is on `origin/main`: `scripts/bootstrap_ci_environment.py` and, for the expected Fuseki image alone, `scripts/verify_external_services.py`. `deploy/bootstrap/compose.yaml` stays unchanged. Another production file, a lock, a schema, or an approved contract stops the code and opens one decision request.

Sealed records that name a file this unit changes are requalified later as regression only. `select_most_recent` on `origin/main` chooses the head named by `supersedes`. No sealed record is rewritten. Head counts do not increase. This commit does not requalify them.

This commit adds exactly one allowlist entry, `reports/assurance/OCOR-DEV-REM-0067-RCCAD/README.md`, to `extension_paths` in `scripts/validate_ocor_development_plan.py`, and updates that script’s pinned sha256 in `reports/planning/OCOR_PLAN_RUN_STATE.json`. Both of those paths are already planning paths. The admission does not change validator behaviour beyond accepting this contract path. Records that pin the validator are not rewritten here; their regression requalification is part of the later code phase above.

Claims stay `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC and Production `NO-GO`.
