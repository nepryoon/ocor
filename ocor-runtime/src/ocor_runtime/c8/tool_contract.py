"""C8 -- MCP Governed Tool Contract and contract-bound tool registry.

OCOR-DEV-REM-0058 (NCP-U10, NCR-C8-004). The Tool Contract is the closed record of ADD v1.3
§3.5 (ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md:1589-1985,
schema ``urn:ocor:schema:mcp-tool-contract:1.2``), held here verbatim and validated with JSON
Schema draft 2020-12, conditional branches included. It is independent of the Tool Binding,
which associates an adapter without changing interface, risk class or approval policy (same
file :1591).

* A contract is admitted only when it is complete and schema-valid and its ``contract_digest``
  is the wire SHA-256 (``sha256:<hex>``) of its RFC 8785 canonical body without that field,
  recomputed here and never taken from the publisher; both schema pins resolve, in the
  ``SchemaCatalog``, to meta-valid schemas whose canonical digest equals the pin. An incomplete
  contract is never exported (Register FR-108 :255).
* Only allow-listed tools are callable: a tool name without a registered binding is
  ``CAPABILITY_DENIED`` and is not an exportable capability (ADD v1.3 :1988).
* Before the adapter runs, the arguments are bound to the adapter's signature and validated
  against the pinned input schema (parameter constraints) and the contract preconditions are
  evaluated, failing closed; after it returns, the output is validated against the pinned
  output schema and returned as tainted, untrusted content with input and output digests for
  provenance; egress is allowed only towards the destinations of the binding, and only while a
  governed invocation runs (Register FR-127 :277; ADD v1.3 §4.3.1 invariants 3 and 4 :3116-3117).
* Every refusal carries a reason code of the closed ``error_codes`` enum (ADD v1.3 :1759-1778).

The legacy ``ocor_runtime.c8_agent.StrictSandbox`` is unchanged: the current tool runtime installs
the registry's governed adapters in its own sandbox.
"""

from __future__ import annotations

import contextvars
import hashlib
import inspect
import json
import re
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from ..errors import OCORError
from ..kernel.canonical import canonical_bytes

TOOL_CONTRACT_SCHEMA_ID = "urn:ocor:schema:mcp-tool-contract:1.2"

# ADD v1.3 §3.5, ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md:1594-1984, verbatim.
TOOL_CONTRACT_SCHEMA: dict[str, Any] = json.loads(
    r'''
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:ocor:schema:mcp-tool-contract:1.2",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "contract_id",
    "version",
    "contract_digest",
    "governed_context_ref",
    "capability_id",
    "input_schema",
    "output_schema",
    "effect_class",
    "risk_class",
    "allowed_autonomy_tiers",
    "preconditions",
    "policy_refs",
    "approval",
    "idempotency",
    "timeout_ms",
    "retry",
    "compensation",
    "provenance_requirements",
    "evidence_requirements",
    "error_codes"
  ],
  "properties": {
    "contract_id": {
      "$ref": "#/$defs/stableId"
    },
    "version": {
      "$ref": "#/$defs/semver"
    },
    "contract_digest": {
      "$ref": "#/$defs/digest"
    },
    "governed_context_ref": {
      "type": "string",
      "pattern": "^urn:sha256:[0-9a-f]{64}$"
    },
    "capability_id": {
      "$ref": "#/$defs/stableId"
    },
    "input_schema": {
      "$ref": "#/$defs/schemaPin"
    },
    "output_schema": {
      "$ref": "#/$defs/schemaPin"
    },
    "effect_class": {
      "enum": [
        "READ_ONLY",
        "ANALYZE",
        "SIMULATE",
        "PROPOSE_ACTION",
        "EXECUTE_APPROVED_ACTION"
      ]
    },
    "risk_class": {
      "enum": [
        "LOW",
        "MEDIUM",
        "HIGH",
        "CRITICAL"
      ]
    },
    "allowed_autonomy_tiers": {
      "type": "array",
      "minItems": 1,
      "uniqueItems": true,
      "items": {
        "enum": [
          "OBSERVE",
          "ANALYZE",
          "SIMULATE",
          "PROPOSE",
          "EXECUTE_APPROVED"
        ]
      }
    },
    "preconditions": {
      "type": "array",
      "items": {
        "$ref": "#/$defs/namedPredicate"
      }
    },
    "policy_refs": {
      "type": "array",
      "minItems": 1,
      "uniqueItems": true,
      "items": {
        "$ref": "#/$defs/stableId"
      }
    },
    "approval": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "mode",
        "self_approval_allowed",
        "timeout_action"
      ],
      "properties": {
        "mode": {
          "enum": [
            "NONE",
            "HUMAN_GATE",
            "DUAL_CONTROL"
          ]
        },
        "self_approval_allowed": {
          "const": false
        },
        "required_approver_roles": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": {
            "$ref": "#/$defs/stableId"
          }
        },
        "independent_approver_count": {
          "type": "integer",
          "minimum": 0,
          "maximum": 2
        },
        "timeout_action": {
          "enum": [
            "DENY",
            "EXPIRE"
          ]
        }
      }
    },
    "idempotency": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "scope",
        "key_required",
        "duplicate_semantics"
      ],
      "properties": {
        "scope": {
          "enum": [
            "NONE",
            "REQUEST",
            "PRINCIPAL",
            "RESOURCE",
            "TENANT"
          ]
        },
        "key_required": {
          "type": "boolean"
        },
        "duplicate_semantics": {
          "enum": [
            "REPLAY_RECEIPT",
            "REJECT_DUPLICATE",
            "NOT_APPLICABLE"
          ]
        }
      }
    },
    "timeout_ms": {
      "type": "integer",
      "minimum": 1,
      "maximum": 300000
    },
    "retry": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "retry_safe",
        "max_attempts"
      ],
      "properties": {
        "retry_safe": {
          "type": "boolean",
          "description": "true solo se l'operazione e provatamente idempotente lato destinatario; un esito ambiguo su retry_safe=false diventa EXECUTION_UNKNOWN e non e ritentabile (ACT-T18, ACT-T19)"
        },
        "max_attempts": {
          "type": "integer",
          "minimum": 1,
          "maximum": 5
        },
        "backoff": {
          "type": "array",
          "minItems": 1,
          "items": {
            "type": "string",
            "pattern": "^PT[0-9]+(\\.[0-9]+)?S$"
          }
        }
      },
      "allOf": [
        {
          "if": {
            "properties": {
              "retry_safe": {
                "const": false
              }
            },
            "required": [
              "retry_safe"
            ]
          },
          "then": {
            "properties": {
              "max_attempts": {
                "const": 1
              }
            }
          }
        }
      ]
    },
    "compensation": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "mode",
        "irreversibility_class"
      ],
      "properties": {
        "mode": {
          "enum": [
            "NOT_APPLICABLE",
            "HUMAN_AUTHORIZED"
          ]
        },
        "compensation_contract_id": {
          "$ref": "#/$defs/stableId"
        },
        "irreversibility_class": {
          "enum": [
            "REVERSIBLE",
            "COMPENSATABLE",
            "IRREVERSIBLE"
          ]
        }
      }
    },
    "provenance_requirements": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "record_input_digest",
        "record_output_digest",
        "record_policy_decision",
        "record_actor_chain",
        "record_tool_binding"
      ],
      "properties": {
        "record_input_digest": {
          "const": true
        },
        "record_output_digest": {
          "const": true
        },
        "record_policy_decision": {
          "const": true
        },
        "record_actor_chain": {
          "const": true
        },
        "record_tool_binding": {
          "const": true
        }
      }
    },
    "evidence_requirements": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "input_evidence",
        "output_evidence",
        "minimum_count"
      ],
      "properties": {
        "input_evidence": {
          "enum": [
            "OPTIONAL",
            "REQUIRED"
          ]
        },
        "output_evidence": {
          "enum": [
            "OPTIONAL",
            "REQUIRED"
          ]
        },
        "minimum_count": {
          "type": "integer",
          "minimum": 0
        }
      }
    },
    "error_codes": {
      "type": "array",
      "minItems": 1,
      "uniqueItems": true,
      "items": {
        "enum": [
          "POLICY_DENIED",
          "AUTHORITY_MISSING",
          "CAPABILITY_DENIED",
          "APPROVAL_REQUIRED",
          "APPROVAL_EXPIRED",
          "CAPABILITY_REVOKED",
          "BUDGET_EXCEEDED",
          "SCHEMA_VIOLATION",
          "STALE_CONTEXT",
          "EMERGENCY_STOP_ACTIVE",
          "EXECUTION_UNKNOWN",
          "COMPENSATION_REQUIRED",
          "COMPENSATION_UNKNOWN"
        ]
      }
    }
  },
  "allOf": [
    {
      "if": {
        "properties": {
          "risk_class": {
            "enum": [
              "HIGH",
              "CRITICAL"
            ]
          }
        },
        "required": [
          "risk_class"
        ]
      },
      "then": {
        "properties": {
          "approval": {
            "properties": {
              "mode": {
                "const": "DUAL_CONTROL"
              },
              "independent_approver_count": {
                "const": 2
              }
            },
            "required": [
              "independent_approver_count"
            ]
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "effect_class": {
            "const": "EXECUTE_APPROVED_ACTION"
          }
        },
        "required": [
          "effect_class"
        ]
      },
      "then": {
        "properties": {
          "allowed_autonomy_tiers": {
            "contains": {
              "const": "EXECUTE_APPROVED"
            }
          },
          "approval": {
            "properties": {
              "mode": {
                "enum": [
                  "HUMAN_GATE",
                  "DUAL_CONTROL"
                ]
              }
            }
          },
          "idempotency": {
            "properties": {
              "scope": {
                "not": {
                  "const": "NONE"
                }
              },
              "key_required": {
                "const": true
              }
            }
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "approval": {
            "properties": {
              "mode": {
                "const": "DUAL_CONTROL"
              }
            },
            "required": [
              "mode"
            ]
          }
        }
      },
      "then": {
        "properties": {
          "approval": {
            "properties": {
              "independent_approver_count": {
                "const": 2
              }
            },
            "required": [
              "independent_approver_count"
            ]
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "compensation": {
            "properties": {
              "mode": {
                "const": "HUMAN_AUTHORIZED"
              }
            },
            "required": [
              "mode"
            ]
          }
        },
        "required": [
          "compensation"
        ]
      },
      "then": {
        "properties": {
          "compensation": {
            "required": [
              "mode",
              "compensation_contract_id",
              "irreversibility_class"
            ]
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "approval": {
            "properties": {
              "mode": {
                "const": "HUMAN_GATE"
              }
            },
            "required": [
              "mode"
            ]
          }
        },
        "required": [
          "approval"
        ]
      },
      "then": {
        "properties": {
          "approval": {
            "properties": {
              "independent_approver_count": {
                "type": "integer",
                "minimum": 1,
                "maximum": 2
              },
              "required_approver_roles": {
                "minItems": 1
              }
            },
            "required": [
              "independent_approver_count",
              "required_approver_roles"
            ]
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "effect_class": {
            "const": "EXECUTE_APPROVED_ACTION"
          }
        },
        "required": [
          "effect_class"
        ]
      },
      "then": {
        "properties": {
          "approval": {
            "properties": {
              "required_approver_roles": {
                "minItems": 1
              }
            },
            "required": [
              "independent_approver_count",
              "required_approver_roles"
            ]
          },
          "evidence_requirements": {
            "properties": {
              "input_evidence": {
                "const": "REQUIRED"
              },
              "minimum_count": {
                "minimum": 1
              }
            }
          },
          "error_codes": {
            "contains": {
              "const": "EXECUTION_UNKNOWN"
            }
          },
          "compensation": {
            "required": [
              "mode",
              "irreversibility_class"
            ]
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "effect_class": {
            "const": "PROPOSE_ACTION"
          }
        },
        "required": [
          "effect_class"
        ]
      },
      "then": {
        "properties": {
          "allowed_autonomy_tiers": {
            "contains": {
              "const": "PROPOSE"
            }
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "effect_class": {
            "const": "SIMULATE"
          }
        },
        "required": [
          "effect_class"
        ]
      },
      "then": {
        "properties": {
          "allowed_autonomy_tiers": {
            "contains": {
              "const": "SIMULATE"
            }
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "effect_class": {
            "const": "ANALYZE"
          }
        },
        "required": [
          "effect_class"
        ]
      },
      "then": {
        "properties": {
          "allowed_autonomy_tiers": {
            "contains": {
              "const": "ANALYZE"
            }
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "effect_class": {
            "const": "READ_ONLY"
          }
        },
        "required": [
          "effect_class"
        ]
      },
      "then": {
        "properties": {
          "allowed_autonomy_tiers": {
            "not": {
              "contains": {
                "const": "EXECUTE_APPROVED"
              }
            }
          }
        }
      }
    }
  ],
  "$defs": {
    "stableId": {
      "type": "string",
      "pattern": "^urn:ocor:[A-Za-z0-9._~:/-]{1,240}$"
    },
    "semver": {
      "type": "string",
      "pattern": "^(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?(?:\\+[0-9A-Za-z.-]+)?$"
    },
    "digest": {
      "type": "string",
      "pattern": "^sha256:[0-9a-f]{64}$"
    },
    "schemaPin": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "schema_id",
        "version",
        "digest"
      ],
      "properties": {
        "schema_id": {
          "$ref": "#/$defs/stableId"
        },
        "version": {
          "$ref": "#/$defs/semver"
        },
        "digest": {
          "$ref": "#/$defs/digest"
        }
      }
    },
    "namedPredicate": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "predicate_id",
        "version",
        "failure_action"
      ],
      "properties": {
        "predicate_id": {
          "$ref": "#/$defs/stableId"
        },
        "version": {
          "$ref": "#/$defs/semver"
        },
        "failure_action": {
          "enum": [
            "DENY",
            "ESCALATE"
          ]
        }
      }
    }
  }
}'''
)
_CONTRACT_VALIDATOR = Draft202012Validator(TOOL_CONTRACT_SCHEMA)

# ADD v1.3 :1759-1778: the closed error_codes enum, in the order of the contract.
TOOL_ERROR_CODES: tuple[str, ...] = tuple(TOOL_CONTRACT_SCHEMA["properties"]["error_codes"]["items"]["enum"])

UNTRUSTED_TOOL_OUTPUT_TAINT: tuple[str, ...] = ("TOOL_OUTPUT", "UNTRUSTED")

_WIRE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_STABLE_ID = re.compile(r"^urn:ocor:[A-Za-z0-9._~:/-]{1,240}$")
_SEMVER = re.compile(TOOL_CONTRACT_SCHEMA["$defs"]["semver"]["pattern"])
_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_DESTINATION = re.compile(r"^[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?$")


class ToolContractError(OCORError):
    """A Tool Contract, binding or call was refused; ``reason_code`` belongs to the closed
    ``error_codes`` enum of the contract (ADD v1.3 :1759-1778)."""

    def __init__(self, reason_code: str, message: str) -> None:
        if reason_code not in TOOL_ERROR_CODES:
            raise ValueError(f"{reason_code!r} is not a Tool Contract error code")
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def wire_digest(value: Any) -> str:
    """``sha256:<hex>`` of the RFC 8785 canonical bytes of an I-JSON value."""
    try:
        return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()
    except Exception as error:  # noqa: BLE001 - every non I-JSON value is a schema violation
        raise ToolContractError("SCHEMA_VIOLATION", "value is not canonical I-JSON") from error


def _violation(message: str) -> ToolContractError:
    return ToolContractError("SCHEMA_VIOLATION", message)


def _first_error(validator: Draft202012Validator, value: Any) -> str | None:
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.absolute_path))
    if not errors:
        return None
    first = errors[0]
    location = "/".join(str(part) for part in first.absolute_path) or "<root>"
    return f"{location}: {first.message}"


@dataclass(frozen=True, slots=True)
class SchemaPin:
    schema_id: str
    version: str
    digest: str


class SchemaCatalog:
    """Schemas a contract may pin, by ``(schema_id, version)``; each schema is meta-validated
    and digested on admission."""

    def __init__(self) -> None:
        self._schemas: dict[tuple[str, str], tuple[str, dict[str, Any], Draft202012Validator]] = {}

    def add(self, schema_id: str, version: str, schema: Mapping[str, Any]) -> str:
        if not isinstance(schema_id, str) or _STABLE_ID.fullmatch(schema_id) is None:
            raise _violation("schema_id is not a stable OCOR identifier")
        if not isinstance(version, str) or _SEMVER.fullmatch(version) is None:
            raise _violation("schema version is not a semantic version")
        if not isinstance(schema, Mapping):
            raise _violation("a schema is a JSON object")
        document = json.loads(json.dumps(dict(schema)))
        try:
            Draft202012Validator.check_schema(document)
        except SchemaError as error:
            raise _violation(f"schema {schema_id}@{version} is not a valid JSON Schema 2020-12: {error.message}") from error
        key = (schema_id, version)
        digest = wire_digest(document)
        known = self._schemas.get(key)
        if known is not None and known[0] != digest:
            raise _violation(f"schema {schema_id}@{version} is already registered with another digest")
        self._schemas[key] = (digest, document, Draft202012Validator(document))
        return digest

    def resolve(self, pin: SchemaPin) -> Draft202012Validator:
        known = self._schemas.get((pin.schema_id, pin.version))
        if known is None:
            raise _violation(f"schema pin {pin.schema_id}@{pin.version} does not resolve")
        if known[0] != pin.digest:
            raise _violation(f"schema {pin.schema_id}@{pin.version} does not have the pinned digest")
        return known[2]


@dataclass(frozen=True, slots=True)
class NamedPredicate:
    predicate_id: str
    version: str
    failure_action: str


@dataclass(frozen=True, slots=True)
class ToolContract:
    """An admitted ``mcp-tool-contract:1.2`` (closed, digest-verified, pins resolved)."""

    contract_id: str
    version: str
    contract_digest: str
    governed_context_ref: str
    capability_id: str
    input_schema: SchemaPin
    output_schema: SchemaPin
    effect_class: str
    risk_class: str
    allowed_autonomy_tiers: tuple[str, ...]
    preconditions: tuple[NamedPredicate, ...]
    policy_refs: tuple[str, ...]
    error_codes: tuple[str, ...]
    timeout_ms: int
    retry_safe: bool
    max_attempts: int
    approval_mode: str
    document: Mapping[str, Any] = field(repr=False, compare=False)
    _input: Draft202012Validator = field(repr=False, compare=False)
    _output: Draft202012Validator = field(repr=False, compare=False)

    @classmethod
    def from_document(cls, document: object, *, schemas: SchemaCatalog) -> ToolContract:
        if not isinstance(document, Mapping):
            raise _violation("a Tool Contract is a JSON object")
        try:
            body = json.loads(json.dumps(dict(document), allow_nan=False))
        except (TypeError, ValueError) as error:
            raise _violation("a Tool Contract is an I-JSON object") from error
        problem = _first_error(_CONTRACT_VALIDATOR, body)
        if problem is not None:
            raise _violation(f"Tool Contract does not conform to {TOOL_CONTRACT_SCHEMA_ID}: {problem}")
        claimed = body["contract_digest"]
        unsealed = {key: value for key, value in body.items() if key != "contract_digest"}
        if wire_digest(unsealed) != claimed:
            raise _violation("contract_digest is not the digest of the contract body")
        input_pin = SchemaPin(**body["input_schema"])
        output_pin = SchemaPin(**body["output_schema"])
        input_validator = schemas.resolve(input_pin)
        output_validator = schemas.resolve(output_pin)
        return cls(
            contract_id=body["contract_id"],
            version=body["version"],
            contract_digest=claimed,
            governed_context_ref=body["governed_context_ref"],
            capability_id=body["capability_id"],
            input_schema=input_pin,
            output_schema=output_pin,
            effect_class=body["effect_class"],
            risk_class=body["risk_class"],
            allowed_autonomy_tiers=tuple(body["allowed_autonomy_tiers"]),
            preconditions=tuple(NamedPredicate(**item) for item in body["preconditions"]),
            policy_refs=tuple(body["policy_refs"]),
            error_codes=tuple(body["error_codes"]),
            timeout_ms=body["timeout_ms"],
            retry_safe=body["retry"]["retry_safe"],
            max_attempts=body["retry"]["max_attempts"],
            approval_mode=body["approval"]["mode"],
            document=body,
            _input=input_validator,
            _output=output_validator,
        )

    def validate_input(self, arguments: Mapping[str, Any]) -> None:
        problem = _first_error(self._input, arguments)
        if problem is not None:
            raise _violation(f"arguments of {self.contract_id} violate the pinned input schema: {problem}")

    def validate_output(self, value: Any) -> None:
        problem = _first_error(self._output, value)
        if problem is not None:
            raise _violation(f"output of {self.contract_id} violates the pinned output schema: {problem}")


@dataclass(frozen=True, slots=True)
class ToolBinding:
    """Associates an adapter with a contract without changing it (ADD v1.3 :1591)."""

    tool_name: str
    binding_id: str
    contract_id: str
    contract_version: str
    contract_digest: str
    adapter: Callable[..., Any] = field(compare=False)
    egress_destinations: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.tool_name, str) or _TOOL_NAME.fullmatch(self.tool_name) is None:
            raise _violation("tool_name is not a lowercase identifier")
        for name in ("binding_id", "contract_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or _STABLE_ID.fullmatch(value) is None:
                raise _violation(f"{name} is not a stable OCOR identifier")
        if not isinstance(self.contract_version, str) or _SEMVER.fullmatch(self.contract_version) is None:
            raise _violation("contract_version is not a semantic version")
        if not isinstance(self.contract_digest, str) or _WIRE_DIGEST.fullmatch(self.contract_digest) is None:
            raise _violation("contract_digest is not a sha256 wire digest")
        if not callable(self.adapter):
            raise _violation("a binding adapter is callable")
        if not isinstance(self.egress_destinations, tuple) or not all(
            isinstance(item, str) and _DESTINATION.fullmatch(item) for item in self.egress_destinations
        ):
            raise _violation("egress_destinations is a tuple of host names")


@dataclass(frozen=True, slots=True)
class ToolOutput:
    """The output of a governed call: schema-valid, tainted and untrusted (never canonical,
    never a grant of Authority), with the digests provenance requires."""

    contract_id: str
    contract_digest: str
    binding_id: str
    tool_name: str
    value: Any
    input_digest: str
    output_digest: str
    taint_labels: tuple[str, ...] = UNTRUSTED_TOOL_OUTPUT_TAINT


Predicate = Callable[[Mapping[str, Any]], object]

_EGRESS: contextvars.ContextVar[tuple[str, frozenset[str]] | None] = contextvars.ContextVar("ocor_c8_tool_egress", default=None)


def egress_checkpoint(destination: str) -> None:
    """Egress policy for a tool adapter: a destination outside the allow-list of the binding
    being invoked, or any egress outside a governed invocation, is ``POLICY_DENIED``."""
    scope = _EGRESS.get()
    if scope is None:
        raise ToolContractError("POLICY_DENIED", "egress outside a governed tool invocation")
    binding_id, allowed = scope
    if not isinstance(destination, str) or destination not in allowed:
        raise ToolContractError("POLICY_DENIED", f"egress to {destination!r} is not allowed for {binding_id}")


@contextmanager
def _egress_scope(binding: ToolBinding) -> Iterator[None]:
    token = _EGRESS.set((binding.binding_id, frozenset(binding.egress_destinations)))
    try:
        yield
    finally:
        _EGRESS.reset(token)


class ToolRegistry:
    """The allow-list of contract-bound tools of one governed context."""

    def __init__(
        self,
        *,
        governed_context_ref: str,
        schemas: SchemaCatalog,
        predicates: Mapping[tuple[str, str], Predicate] | None = None,
    ) -> None:
        if not isinstance(governed_context_ref, str) or re.fullmatch(r"^urn:sha256:[0-9a-f]{64}$", governed_context_ref) is None:
            raise _violation("governed_context_ref is not a SHA-256 URN")
        if not isinstance(schemas, SchemaCatalog):
            raise TypeError("schemas must be a SchemaCatalog")
        self._context_ref = governed_context_ref
        self._schemas = schemas
        self._predicates = dict(predicates or {})
        self._tools: dict[str, tuple[ToolContract, ToolBinding]] = {}

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def export(self) -> tuple[ToolContract, ...]:
        """The exportable capabilities: the admitted contracts of the allow-listed tools."""
        return tuple(self._tools[name][0] for name in self.tool_names)

    def register(self, contract: ToolContract, binding: ToolBinding) -> None:
        if not isinstance(contract, ToolContract) or not isinstance(binding, ToolBinding):
            raise _violation("only an admitted ToolContract with a ToolBinding can be registered")
        # re-admitted here: the registry never trusts a contract object it did not validate
        admitted = ToolContract.from_document(contract.document, schemas=self._schemas)
        if (binding.contract_id, binding.contract_version, binding.contract_digest) != (
            admitted.contract_id,
            admitted.version,
            admitted.contract_digest,
        ):
            raise _violation(f"binding {binding.binding_id} does not bind contract {admitted.contract_id}@{admitted.version}")
        if admitted.governed_context_ref != self._context_ref:
            raise ToolContractError("STALE_CONTEXT", f"contract {admitted.contract_id} is bound to another governed context")
        if binding.tool_name in self._tools:
            raise _violation(f"tool {binding.tool_name!r} is already bound")
        self._tools[binding.tool_name] = (admitted, binding)

    def contract(self, tool_name: str) -> ToolContract:
        entry = self._tools.get(tool_name) if isinstance(tool_name, str) else None
        if entry is None:
            raise ToolContractError("CAPABILITY_DENIED", f"tool {tool_name!r} is not allow-listed")
        return entry[0]

    def binding(self, tool_name: str) -> ToolBinding:
        self.contract(tool_name)
        return self._tools[tool_name][1]

    def arguments(self, tool_name: str, args: tuple[Any, ...], kwargs: Mapping[str, Any]) -> dict[str, Any]:
        """Bind a call to the adapter signature and validate it against the input schema."""
        contract = self.contract(tool_name)
        adapter = self._tools[tool_name][1].adapter
        try:
            bound = inspect.signature(adapter).bind(*args, **kwargs)
        except TypeError as error:
            raise _violation(f"call of {tool_name!r} does not match its parameters: {error}") from error
        if any(
            parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
            for parameter in inspect.signature(adapter).parameters.values()
        ):
            raise _violation(f"adapter of {tool_name!r} declares variadic parameters")
        arguments = dict(bound.arguments)
        contract.validate_input(arguments)
        wire_digest(arguments)
        return arguments

    def check_preconditions(self, tool_name: str, arguments: Mapping[str, Any]) -> None:
        for predicate in self.contract(tool_name).preconditions:
            evaluate = self._predicates.get((predicate.predicate_id, predicate.version))
            outcome: object = None
            if evaluate is not None:
                try:
                    outcome = evaluate(dict(arguments))
                except Exception:  # noqa: BLE001 - a failing predicate is never a pass
                    outcome = None
            if outcome is True:
                continue
            if evaluate is not None and outcome is False and predicate.failure_action == "ESCALATE":
                raise ToolContractError("APPROVAL_REQUIRED", f"precondition {predicate.predicate_id} requires escalation")
            raise ToolContractError("POLICY_DENIED", f"precondition {predicate.predicate_id}@{predicate.version} does not hold")

    def invoke(self, tool_name: str, args: tuple[Any, ...], kwargs: Mapping[str, Any]) -> ToolOutput:
        """One governed call: allow-list, parameter constraints and preconditions before the
        adapter; egress scope during it; output schema, taint and digests after it."""
        contract = self.contract(tool_name)
        binding = self._tools[tool_name][1]
        arguments = self.arguments(tool_name, args, kwargs)
        self.check_preconditions(tool_name, arguments)
        with _egress_scope(binding):
            value = binding.adapter(**arguments)
        contract.validate_output(value)
        return ToolOutput(
            contract_id=contract.contract_id,
            contract_digest=contract.contract_digest,
            binding_id=binding.binding_id,
            tool_name=tool_name,
            value=value,
            input_digest=wire_digest(arguments),
            output_digest=wire_digest(value),
        )
