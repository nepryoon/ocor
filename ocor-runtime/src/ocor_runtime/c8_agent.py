"""C8 — strict expression sandbox, token budgets and Identify-or-Abstain kernel."""

from __future__ import annotations

import ast
import copy
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Mapping, Protocol

from .c2_identity import IdentityRegistry, ResolutionStatus
from .c3_store import require_aware
from .c6_capabilities import CapabilityAuthority, CapabilityLease
from .canonical import canonicalize_json
from .errors import AuthorizationError, SandboxViolation, TokenBudgetExceeded

_TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", re.UNICODE)
_SAFE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_FORBIDDEN_TOOL_NAMES = {
    "breakpoint",
    "compile",
    "eval",
    "exec",
    "globals",
    "help",
    "input",
    "locals",
    "open",
    "vars",
    "__import__",
}


def deterministic_token_count(text: str) -> int:
    """Deterministic local counter used when no model tokenizer is supplied."""

    if not isinstance(text, str):
        raise TypeError("token counting input must be text")
    return len(_TOKEN_PATTERN.findall(text))


@dataclass(frozen=True, slots=True)
class TokenCharge:
    category: str
    tokens: int


@dataclass(frozen=True, slots=True)
class BudgetReservation:
    reservation_id: str
    category: str
    tokens: int


class TokenBudget:
    """Thread-safe budget with preflight reservations for model output."""

    def __init__(
        self,
        limit: int,
        *,
        tokenizer: Callable[[str], int] = deterministic_token_count,
    ) -> None:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
            raise ValueError("token limit must be a non-negative integer")
        self.limit = limit
        self._tokenizer = tokenizer
        self._used = 0
        self._reservations: dict[str, BudgetReservation] = {}
        self._charges: list[TokenCharge] = []
        self._lock = threading.RLock()

    @property
    def used(self) -> int:
        with self._lock:
            return self._used

    @property
    def reserved(self) -> int:
        with self._lock:
            return sum(item.tokens for item in self._reservations.values())

    @property
    def remaining(self) -> int:
        with self._lock:
            return self.limit - self._used - sum(
                item.tokens for item in self._reservations.values()
            )

    @property
    def charges(self) -> tuple[TokenCharge, ...]:
        with self._lock:
            return tuple(self._charges)

    def count(self, text: str) -> int:
        count = self._tokenizer(text)
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError("tokenizer must return a non-negative integer")
        return count

    def consume(self, tokens: int, *, category: str) -> TokenCharge:
        if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens < 0:
            raise ValueError("token charge must be a non-negative integer")
        if not category:
            raise ValueError("token category must be non-empty")
        with self._lock:
            if tokens > self.remaining:
                raise TokenBudgetExceeded(
                    f"{category} requires {tokens} tokens; {self.remaining} remain"
                )
            charge = TokenCharge(category, tokens)
            self._used += tokens
            self._charges.append(charge)
            return charge

    def consume_text(self, text: str, *, category: str) -> TokenCharge:
        return self.consume(self.count(text), category=category)

    def reserve(self, tokens: int, *, category: str) -> BudgetReservation:
        if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens < 0:
            raise ValueError("reservation must be a non-negative integer")
        with self._lock:
            if tokens > self.remaining:
                raise TokenBudgetExceeded(
                    f"{category} reservation requires {tokens} tokens; "
                    f"{self.remaining} remain"
                )
            reservation = BudgetReservation(str(uuid.uuid4()), category, tokens)
            self._reservations[reservation.reservation_id] = reservation
            return reservation

    def commit(self, reservation: BudgetReservation, *, used: int) -> TokenCharge:
        if not isinstance(used, int) or isinstance(used, bool) or used < 0:
            raise ValueError("used token count must be a non-negative integer")
        with self._lock:
            authoritative = self._reservations.get(reservation.reservation_id)
            if authoritative != reservation:
                raise ValueError("token reservation is unknown or already closed")
            if used > reservation.tokens:
                raise TokenBudgetExceeded(
                    f"model used {used} tokens beyond its {reservation.tokens}-token reservation"
                )
            del self._reservations[reservation.reservation_id]
            charge = TokenCharge(reservation.category, used)
            self._used += used
            self._charges.append(charge)
            return charge

    def cancel(self, reservation: BudgetReservation) -> None:
        with self._lock:
            self._reservations.pop(reservation.reservation_id, None)


ToolDispatch = Callable[[str, Callable[[], Any]], Any]


class StrictSandbox:
    """A small AST interpreter with no imports, attributes, mutation or builtins."""

    def __init__(
        self,
        tools: Mapping[str, Callable[..., Any]] | None = None,
        *,
        max_source_characters: int = 4096,
        max_ast_nodes: int = 256,
        max_operations: int = 1024,
        max_result_characters: int = 65_536,
    ) -> None:
        if min(
            max_source_characters,
            max_ast_nodes,
            max_operations,
            max_result_characters,
        ) <= 0:
            raise ValueError("sandbox limits must be positive")
        self.max_source_characters = max_source_characters
        self.max_ast_nodes = max_ast_nodes
        self.max_operations = max_operations
        self.max_result_characters = max_result_characters
        self._tools: dict[str, Callable[..., Any]] = {}
        for name, tool in (tools or {}).items():
            self.register_tool(name, tool)

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def register_tool(self, name: str, tool: Callable[..., Any]) -> None:
        if (
            not isinstance(name, str)
            or _SAFE_NAME.fullmatch(name) is None
            or name in _FORBIDDEN_TOOL_NAMES
            or name.startswith("_")
        ):
            raise SandboxViolation(f"unsafe tool name: {name!r}")
        if not callable(tool):
            raise TypeError("sandbox tools must be callable")
        if name in self._tools:
            raise SandboxViolation(f"sandbox tool is already registered: {name!r}")
        self._tools[name] = tool

    def execute(
        self,
        expression: str,
        bindings: Mapping[str, Any] | None = None,
        *,
        dispatch: ToolDispatch | None = None,
    ) -> Any:
        """Evaluate ``expression``. When ``dispatch`` is given, every
        registered tool call is handed to it as ``dispatch(name, call)``
        instead of being called directly: the hook decides whether and how
        ``call`` runs, and any exception it raises propagates unchanged."""
        if not isinstance(expression, str) or not expression.strip():
            raise SandboxViolation("sandbox input must be a non-empty expression")
        if len(expression) > self.max_source_characters:
            raise SandboxViolation("sandbox source-size limit exceeded")
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as exc:
            raise SandboxViolation(f"sandbox accepts expressions only: {exc.msg}") from exc
        if sum(1 for _ in ast.walk(tree)) > self.max_ast_nodes:
            raise SandboxViolation("sandbox AST-size limit exceeded")
        stable_bindings = copy.deepcopy(dict(bindings or {}))
        for name in stable_bindings:
            if _SAFE_NAME.fullmatch(name) is None or name.startswith("_"):
                raise SandboxViolation(f"unsafe binding name: {name!r}")
        evaluator = _ExpressionEvaluator(
            stable_bindings,
            self._tools,
            operations=self.max_operations,
            max_result_characters=self.max_result_characters,
            dispatch=dispatch,
        )
        return evaluator.evaluate(tree.body)


class _ExpressionEvaluator:
    _BINARY_OPERATORS: Mapping[type[ast.operator], Callable[[Any, Any], Any]] = {
        ast.Add: lambda left, right: left + right,
        ast.Sub: lambda left, right: left - right,
        ast.Mult: lambda left, right: left * right,
        ast.Div: lambda left, right: left / right,
        ast.FloorDiv: lambda left, right: left // right,
        ast.Mod: lambda left, right: left % right,
        ast.Pow: lambda left, right: left**right,
    }
    _COMPARISONS: Mapping[type[ast.cmpop], Callable[[Any, Any], bool]] = {
        ast.Eq: lambda left, right: left == right,
        ast.NotEq: lambda left, right: left != right,
        ast.Lt: lambda left, right: left < right,
        ast.LtE: lambda left, right: left <= right,
        ast.Gt: lambda left, right: left > right,
        ast.GtE: lambda left, right: left >= right,
        ast.In: lambda left, right: left in right,
        ast.NotIn: lambda left, right: left not in right,
    }

    def __init__(
        self,
        bindings: Mapping[str, Any],
        tools: Mapping[str, Callable[..., Any]],
        *,
        operations: int,
        max_result_characters: int,
        dispatch: ToolDispatch | None = None,
    ) -> None:
        self.bindings = bindings
        self.tools = tools
        self.operations = operations
        self.max_result_characters = max_result_characters
        self.dispatch = dispatch

    def _spend(self) -> None:
        self.operations -= 1
        if self.operations < 0:
            raise SandboxViolation("sandbox operation budget exceeded")

    def _bounded(self, value: Any) -> Any:
        try:
            rendered = canonicalize_json(value)
        except Exception as exc:
            raise SandboxViolation("sandbox result is not safe I-JSON") from exc
        if len(rendered) > self.max_result_characters:
            raise SandboxViolation("sandbox result-size limit exceeded")
        return value

    def evaluate(self, node: ast.AST) -> Any:  # noqa: C901 - explicit whitelist is intentional
        self._spend()
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (str, int, float, bool, type(None))):
                raise SandboxViolation("unsupported literal type")
            return self._bounded(node.value)
        if isinstance(node, ast.Name):
            if node.id not in self.bindings:
                raise SandboxViolation(f"unknown sandbox binding: {node.id!r}")
            return copy.deepcopy(self.bindings[node.id])
        if isinstance(node, ast.List):
            return self._bounded([self.evaluate(item) for item in node.elts])
        if isinstance(node, ast.Tuple):
            return self._bounded([self.evaluate(item) for item in node.elts])
        if isinstance(node, ast.Dict):
            if any(key is None for key in node.keys):
                raise SandboxViolation("dictionary unpacking is forbidden")
            keys = [self.evaluate(key) for key in node.keys if key is not None]
            if not all(isinstance(key, str) for key in keys):
                raise SandboxViolation("sandbox dictionary keys must be strings")
            if len(set(keys)) != len(keys):
                raise SandboxViolation("duplicate sandbox dictionary key")
            return self._bounded(
                {key: self.evaluate(value) for key, value in zip(keys, node.values)}
            )
        if isinstance(node, ast.UnaryOp):
            operand = self.evaluate(node.operand)
            if isinstance(node.op, ast.Not):
                return not operand
            if isinstance(node.op, ast.UAdd) and isinstance(operand, (int, float)):
                return self._bounded(+operand)
            if isinstance(node.op, ast.USub) and isinstance(operand, (int, float)):
                return self._bounded(-operand)
            raise SandboxViolation("unsupported unary operation")
        if isinstance(node, ast.BinOp):
            operation = self._BINARY_OPERATORS.get(type(node.op))
            if operation is None:
                raise SandboxViolation("unsupported binary operation")
            left, right = self.evaluate(node.left), self.evaluate(node.right)
            if isinstance(node.op, ast.Pow) and (
                not isinstance(right, int) or abs(right) > 16
            ):
                raise SandboxViolation("unsafe exponent")
            try:
                return self._bounded(operation(left, right))
            except SandboxViolation:
                raise
            except Exception as exc:
                raise SandboxViolation(f"binary operation failed: {exc}") from exc
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                result: Any = True
                for item in node.values:
                    result = self.evaluate(item)
                    if not result:
                        return result
                return result
            if isinstance(node.op, ast.Or):
                result = False
                for item in node.values:
                    result = self.evaluate(item)
                    if result:
                        return result
                return result
            raise SandboxViolation("unsupported boolean operation")
        if isinstance(node, ast.Compare):
            left = self.evaluate(node.left)
            for operator, comparator_node in zip(node.ops, node.comparators):
                operation = self._COMPARISONS.get(type(operator))
                if operation is None:
                    raise SandboxViolation("unsupported comparison")
                right = self.evaluate(comparator_node)
                try:
                    if not operation(left, right):
                        return False
                except Exception as exc:
                    raise SandboxViolation(f"comparison failed: {exc}") from exc
                left = right
            return True
        if isinstance(node, ast.IfExp):
            return self.evaluate(node.body if self.evaluate(node.test) else node.orelse)
        if isinstance(node, ast.Subscript):
            target = self.evaluate(node.value)
            if isinstance(node.slice, ast.Slice):
                lower = self.evaluate(node.slice.lower) if node.slice.lower else None
                upper = self.evaluate(node.slice.upper) if node.slice.upper else None
                step = self.evaluate(node.slice.step) if node.slice.step else None
                key: Any = slice(lower, upper, step)
            else:
                key = self.evaluate(node.slice)
            try:
                return self._bounded(copy.deepcopy(target[key]))
            except Exception as exc:
                raise SandboxViolation(f"subscript failed: {exc}") from exc
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in self.tools:
                raise SandboxViolation("only registered tool calls are allowed")
            if any(isinstance(arg, ast.Starred) for arg in node.args):
                raise SandboxViolation("argument unpacking is forbidden")
            if any(keyword.arg is None for keyword in node.keywords):
                raise SandboxViolation("keyword unpacking is forbidden")
            args = [self.evaluate(argument) for argument in node.args]
            kwargs = {
                str(keyword.arg): self.evaluate(keyword.value)
                for keyword in node.keywords
            }
            name = node.func.id
            tool = self.tools[name]

            def call() -> Any:
                try:
                    return tool(*copy.deepcopy(args), **copy.deepcopy(kwargs))
                except Exception as exc:
                    raise SandboxViolation(f"sandbox tool {name!r} failed: {exc}") from exc

            result = call() if self.dispatch is None else self.dispatch(name, call)
            return self._bounded(copy.deepcopy(result))
        raise SandboxViolation(f"forbidden syntax: {type(node).__name__}")


class AgentDecision(str, Enum):
    IDENTIFY = "IDENTIFY"
    ABSTAIN = "ABSTAIN"


@dataclass(frozen=True, slots=True)
class AgentResponse:
    decision: AgentDecision
    identity_id: str | None
    confidence: float
    reason: str
    content: Any = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("agent confidence must be between zero and one")
        if not self.reason:
            raise ValueError("agent reason must be non-empty")
        if self.decision is AgentDecision.IDENTIFY and not self.identity_id:
            raise ValueError("IDENTIFY requires identity_id")
        if self.decision is AgentDecision.ABSTAIN and self.identity_id is not None:
            raise ValueError("ABSTAIN cannot assert an identity")


@dataclass(frozen=True, slots=True)
class ModelResult:
    response: AgentResponse | Mapping[str, Any]
    output_tokens: int | None = None


class AgentModel(Protocol):
    def __call__(self, prompt: str, *, max_output_tokens: int) -> ModelResult: ...


class AgentKernel:
    """Fail-closed kernel: authorized invocation, bounded output, structured result."""

    def __init__(
        self,
        *,
        identity_registry: IdentityRegistry | None = None,
        sandbox: StrictSandbox | None = None,
        capability_authority: CapabilityAuthority | None = None,
        subject: str = "ocor-agent",
    ) -> None:
        self.identity_registry = identity_registry or IdentityRegistry()
        self.sandbox = sandbox or StrictSandbox()
        self.capability_authority = capability_authority
        self.subject = subject

    def identify_or_abstain(
        self,
        identifier: str,
        *,
        budget: TokenBudget | None = None,
        evidence: Mapping[str, float] | None = None,
        minimum_confidence: float = 0.80,
        minimum_margin: float = 0.10,
    ) -> AgentResponse:
        if budget is not None:
            budget.consume_text(identifier, category="identity-input")
        outcome = self.identity_registry.resolve(
            identifier,
            evidence=evidence,
            minimum_confidence=minimum_confidence,
            minimum_margin=minimum_margin,
        )
        if outcome.status is ResolutionStatus.IDENTIFIED:
            return AgentResponse(
                AgentDecision.IDENTIFY,
                outcome.canonical_id,
                outcome.confidence,
                outcome.reason,
            )
        return AgentResponse(
            AgentDecision.ABSTAIN,
            None,
            outcome.confidence,
            outcome.reason,
            {"candidates": list(outcome.candidates)},
        )

    def execute_sandboxed(
        self,
        expression: str,
        *,
        bindings: Mapping[str, Any] | None = None,
        lease: CapabilityLease | str | None = None,
        at: datetime | None = None,
    ) -> Any:
        if self.capability_authority is not None:
            if lease is None or at is None:
                raise AuthorizationError("sandbox execution requires a capability lease and time")
            self.capability_authority.authorize(
                lease,
                "agent:sandbox",
                self.subject,
                at=require_aware(at, field="at"),
                subject=self.subject,
                consume=True,
            )
        return self.sandbox.execute(expression, bindings)

    @staticmethod
    def _coerce_response(value: AgentResponse | Mapping[str, Any]) -> AgentResponse:
        if isinstance(value, AgentResponse):
            return value
        if not isinstance(value, Mapping):
            raise SandboxViolation("agent model must return a structured response")
        try:
            decision = AgentDecision(str(value["decision"]))
            identity_id = value.get("identityId", value.get("identity_id"))
            return AgentResponse(
                decision=decision,
                identity_id=identity_id,
                confidence=float(value["confidence"]),
                reason=str(value["reason"]),
                content=copy.deepcopy(value.get("content")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SandboxViolation(f"invalid structured agent response: {exc}") from exc

    def invoke(
        self,
        prompt: str,
        model: AgentModel,
        *,
        budget: TokenBudget,
        max_output_tokens: int,
        lease: CapabilityLease | str | None = None,
        at: datetime | None = None,
    ) -> AgentResponse:
        if max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        budget.consume_text(prompt, category="model-input")
        reservation = budget.reserve(max_output_tokens, category="model-output")
        try:
            if self.capability_authority is not None:
                if lease is None or at is None:
                    raise AuthorizationError(
                        "agent invocation requires a capability lease and time"
                    )
                self.capability_authority.authorize(
                    lease,
                    "agent:invoke",
                    self.subject,
                    at=require_aware(at, field="at"),
                    subject=self.subject,
                    consume=True,
                )
            model_result = model(prompt, max_output_tokens=max_output_tokens)
            if not isinstance(model_result, ModelResult):
                model_result = ModelResult(model_result)
            response = self._coerce_response(model_result.response)
            rendered = canonicalize_json(
                {
                    "decision": response.decision.value,
                    "identityId": response.identity_id,
                    "confidence": response.confidence,
                    "reason": response.reason,
                    "content": response.content,
                }
            )
            measured = budget.count(rendered)
            declared = model_result.output_tokens
            if declared is not None and declared < measured:
                raise TokenBudgetExceeded(
                    "model-reported output usage is lower than deterministic measurement"
                )
            used = max(measured, declared or 0)
            budget.commit(reservation, used=used)
            return response
        except Exception:
            budget.cancel(reservation)
            raise


Sandbox = StrictSandbox
