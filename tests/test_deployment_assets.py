"""Deployment bundle checks for the currently approved PiCare assets."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.verify_deployment_assets import VerificationError, verify


def test_current_runpod_and_aws_assets_are_consistent():
    report = verify(ROOT, target="all", skip_adapter=True)

    assert report["runpod"]["documents"] == 23
    assert report["runpod"]["chunks"] == 381
    assert report["runpod"]["indexed_chunks"] == 381
    assert report["runpod"]["api_port"] == 8000
    assert report["aws"]["command_templates"] == 100


def test_production_runpod_check_requires_lora_adapter():
    with pytest.raises(VerificationError, match="LoRA adapter path is required"):
        verify(ROOT, target="runpod")


def test_adapter_check_rejects_config_without_weights(tmp_path):
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "adapter_config.json").write_text(json.dumps({"base_model_name_or_path": "Qwen"}))

    with pytest.raises(VerificationError, match="adapter weights are missing"):
        verify(ROOT, target="runpod", adapter_path=adapter)
