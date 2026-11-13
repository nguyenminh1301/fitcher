"""The optional screening classifier as the Models page and the setup show it (DECISIONS §9)."""

from app.contracts.query_spec import ContractModel


class ClassifierStatus(ContractModel):
    # Turned on: every question is also scored by the classifier, and screening fails closed without it.
    enabled: bool
    # The exported model is in the guard model directory.
    model_present: bool
    version: str | None
