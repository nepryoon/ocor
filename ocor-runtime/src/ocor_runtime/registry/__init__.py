"""Function & Model Registry -- the ``ocor.registry.v1`` contract (LLD v1.1 §0.2, ADD v1.3 §3.4).

``contract`` mirrors the messages and enums of
``ocor-runtime/docs/governance_dossier/contracts/ocor_registry.proto`` field by field;
``service`` realises the ``FunctionRegistry`` and ``ModelRegistry`` operations and the
admission constraints of ADD v1.3 §3.4; ``sandbox`` executes Function and Model
artefacts under the budget of NFR-025; ``adapters.postgres`` is the PostgreSQL
persistence of the registry (append-only entries, lineage and audit).
"""
