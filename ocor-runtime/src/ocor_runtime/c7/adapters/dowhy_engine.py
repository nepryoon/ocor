"""C7 engine adapter on DoWhy (PyWhy), the causal configuration item of ADD v1.3 :275.

OCOR-DEV-REM-0057 (NCP-U09). Identification runs on DoWhy's identifier over the graph
of the registered SCM, with the exogenous variables unobserved: an exogenous variable
shared by the treatment and the outcome is an unobserved confounder, and the estimand is
identified only when a backdoor adjustment set of observed variables exists. Action
(``do``) and prediction work on the registered mechanisms ``F`` and ``P(U)``; abduction
is the deferred ``ELM-070`` of the PoC profile (ADD v1.3 :3036).

DoWhy is imported lazily and only here, behind ``CausalEnginePort``; it makes no network
access and the prediction is deterministic for a given seed.
"""

from __future__ import annotations

import functools
import importlib
import math
import statistics
from collections.abc import Mapping, Sequence
from decimal import Decimal
from types import ModuleType
from typing import Any

from ..runtime import (
    COUNTERFACTUAL_ELEMENT,
    CapabilityDeferredError,
    Identification,
    Prediction,
    StructuralCausalModel,
)


@functools.cache
def _module(name: str) -> ModuleType:
    return importlib.import_module(name)


class DoWhyCausalEngine:
    """``CausalEnginePort`` on DoWhy."""

    def identify(self, model: StructuralCausalModel, *, treatment: str, outcome: str) -> Identification:
        networkx = _module("networkx")
        identifier = _module("dowhy.causal_identifier")
        graph = networkx.DiGraph()
        graph.add_nodes_from(sorted({*model.exogenous, *model.endogenous}))
        graph.add_edges_from(model.edges())
        estimand = identifier.identify_effect_auto(
            graph,
            action_nodes=[treatment],
            outcome_nodes=[outcome],
            observed_nodes=list(model.observed),
            estimand_type=identifier.EstimandType.NONPARAMETRIC_ATE,
            backdoor_adjustment=identifier.BackdoorAdjustment.BACKDOOR_DEFAULT,
        )
        backdoor = estimand.backdoor_variables.get("backdoor") if estimand.backdoor_variables else None
        available = sorted(
            name for name in ("frontdoor", "iv") if getattr(estimand, f"{'instrumental' if name == 'iv' else name}_variables", None)
        )
        if backdoor is None:
            return Identification(
                identified=False,
                method=None,
                adjustment_set=(),
                diagnostics={
                    "identification_test": "backdoor_criterion",
                    "backdoor_adjustment_set_found": False,
                    "other_identification_strategies": available,
                    "engine": "dowhy",
                },
            )
        return Identification(
            identified=True,
            method="backdoor",
            adjustment_set=tuple(sorted(str(name) for name in backdoor)),
            diagnostics={"identification_test": "backdoor_criterion", "backdoor_adjustment_set_found": True, "engine": "dowhy"},
        )

    def abduct(self, model: StructuralCausalModel, factual_rows: Sequence[Mapping[str, Any]]) -> StructuralCausalModel:
        raise CapabilityDeferredError(COUNTERFACTUAL_ELEMENT)

    def act(self, model: StructuralCausalModel, assignments: Mapping[str, Decimal]) -> StructuralCausalModel:
        return model.do(assignments)

    def predict(self, model: StructuralCausalModel, *, outcome: str, seed: int, size: int) -> Prediction:
        values = [row[outcome] for row in model.sample(seed=seed, size=size)]
        mean = math.fsum(values) / len(values)
        deviation = statistics.pstdev(values, mu=mean)
        return Prediction(
            outcome=outcome,
            mean=Decimal(repr(round(mean, 6))).normalize(),
            standard_deviation=Decimal(repr(round(deviation, 6))).normalize(),
            size=size,
        )
