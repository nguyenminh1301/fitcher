"""The guard model fetch job, without Hugging Face, PyTorch or the gated model."""

import pytest

from jobs import fetch_guard_model as job


@pytest.mark.parametrize(("config", "index"), [
    ({"id2label": {"0": "BENIGN", "1": "MALICIOUS"}}, 1),
    ({"id2label": {"0": "INJECTION", "1": "BENIGN"}}, 0),
    ({"id2label": {"0": "LABEL_0", "1": "LABEL_1"}}, 1),
    ({"num_labels": 2}, 1),
])
def test_malicious_label_index(config, index):
    assert job.malicious_index(config) == index


def test_an_unclear_label_set_is_refused():
    with pytest.raises(job.FetchError, match="cannot tell the malicious label"):
        job.malicious_index({"id2label": {"0": "BENIGN", "1": "INJECTION", "2": "JAILBREAK"}})


def test_without_a_token_the_job_stops_before_any_download(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setattr(job, "fetch", lambda args, token: pytest.fail("must not download"))

    assert job.main(["--output", str(tmp_path)]) == 1
    assert "HF_TOKEN must be set" in capsys.readouterr().err


def test_a_failure_is_reported_without_the_token(monkeypatch, capsys, tmp_path):
    secret = "hf_" + "x" * 34
    monkeypatch.setenv("HF_TOKEN", secret)

    def refuse(args, token):
        assert token == secret
        raise job.FetchError("Hugging Face refused meta-llama/Llama-Prompt-Guard-2-86M@main (HTTP 403)")

    monkeypatch.setattr(job, "fetch", refuse)

    assert job.main(["--output", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert "HTTP 403" in captured.err and secret not in captured.err + captured.out
