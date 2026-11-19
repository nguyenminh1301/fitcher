"""The optional screening classifier as the Security page and the setup show it (DECISIONS §9)."""

from typing import Literal

from app.contracts.query_spec import ContractModel

ClassifierEngine = Literal["provider", "local_onnx"]


class ClassifierDownload(ContractModel):
    # idle, downloading, checking, done, failed or cancelled
    state: Literal["idle", "downloading", "checking", "done", "failed", "cancelled"]
    bytes_done: int
    bytes_total: int
    error: str | None = None


class ClassifierStatus(ContractModel):
    # Turned on: every question is also scored by the classifier, and screening fails closed without it.
    enabled: bool
    # The ONNX model is in the guard model directory, for the on-this-computer engine.
    model_present: bool
    version: str | None
    # provider: a Prompt Guard model of a configured provider; local_onnx: the downloaded model on this computer.
    engine: ClassifierEngine = "provider"
    provider_id: str | None = None
    model: str | None = None
    # The download of the model for the on-this-computer engine, while one runs or after it ended.
    download: ClassifierDownload | None = None
    # Where the downloaded model comes from and its licence.
    download_source: str | None = None
    license: str | None = None


class ClassifierChange(ContractModel):
    enabled: bool
    engine: ClassifierEngine = "provider"
    # The provider and model of the provider engine; the model defaults to Llama Prompt Guard 2 86M.
    provider_id: str | None = None
    model: str | None = None
