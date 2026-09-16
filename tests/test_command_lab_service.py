from copy import deepcopy

import pytest

from document_pipeline.ingestion.build_command_catalog import parts_for
from src.services.command_lab_service import CommandLabError, CommandLabService


@pytest.fixture
def lab():
    return CommandLabService()


def test_approved_only_and_audit(lab):
    audit = lab.audit()
    assert audit["total"] == 100
    assert audit["approved"] + audit["draft"] == audit["total"]
    assert audit["errors"] == []
    assert len(lab.list_templates()) == audit["approved"]
    draft = next(item for item in lab.templates.values() if item["review_status"] != "approved")
    with pytest.raises(CommandLabError):
        lab.compose(draft["template_id"])


def test_every_approved_command_roundtrip(lab):
    for item in lab.list_templates():
        result = lab.analyze(item["canonical_command"])
        assert result["command"] == item["canonical_command"]
        assert result["execution_policy"] == "display_only"
        assert result["evidence"]


def test_edit_ssh_and_analyze_roundtrip(lab):
    result = lab.compose("cmd-remote-access-004", {"part-02": "pi@192.168.0.12"}, product_id="raspberry-pi-5")
    assert result["command"] == "ssh pi@192.168.0.12"
    assert result["product"]["name"] == "Raspberry Pi 5"
    assert lab.analyze(result["command"])["values"] == {"part-02": "pi@192.168.0.12"}


@pytest.mark.parametrize("value", ["", "x" * 161, "pi@host; reboot", "pi@host\nreboot", "$(id)",
                                     "`id`", "pi@host|cat", "pi@host && id", "-oProxyCommand=id", "pi@host extra"])
def test_input_injection_and_invalid_values_rejected(lab, value):
    with pytest.raises(CommandLabError):
        lab.compose("cmd-remote-access-004", {"part-02": value})


@pytest.mark.parametrize("values", [{"part-01": "rm"}, [], "pi@host", {"part-02": None}])
def test_fixed_and_invalid_fields_rejected(lab, values):
    with pytest.raises(CommandLabError):
        lab.compose("cmd-remote-access-004", values)


@pytest.mark.parametrize("command", ["rm -rf /", "sudo raspi-config; reboot", "ssh 'pi@host", "ls /", ""])
def test_unknown_commands_rejected(lab, command):
    with pytest.raises(CommandLabError):
        lab.analyze(command)


def test_missing_or_changed_evidence_excluded(lab):
    key = lab.templates["cmd-remote-access-004"]["evidence_ids"][0]
    lab.chunks[key]["chunk_checksum"] = "sha256:changed"
    assert "cmd-remote-access-004" not in {t["template_id"] for t in lab.list_templates()}
    with pytest.raises(CommandLabError):
        lab.compose("cmd-remote-access-004")
    assert lab.audit()["errors"]


def test_drawer_revalidates_snapshot_and_evidence(lab):
    saved = lab.drawer_payload("cmd-remote-access-004", {"part-02": "pi@host"}, product_id="raspberry-pi-5")
    assert lab.restore_drawer(saved)["command"] == "ssh pi@host"
    for key in ("catalog_version", "command_checksum", "command_snapshot", "evidence_checksums"):
        changed = deepcopy(saved)
        changed[key] = "tampered"
        with pytest.raises(CommandLabError):
            lab.restore_drawer(changed)


def test_unknown_product_rejected(lab):
    with pytest.raises(CommandLabError):
        lab.compose("cmd-remote-access-004", product_id="invented-board")


def test_tokenizer_preserves_placeholder_with_spaces():
    parts, fields = parts_for("scp .ssh/id_rsa.pub <username>@<ip address>:.ssh/authorized_keys")
    assert len(parts) == 3
    assert parts[-1]["value"] == "<username>@<ip address>:.ssh/authorized_keys"
    assert fields[0]["part_id"] == "part-03"


def test_ssh_settings_evidence_is_ssh_document(lab):
    assert all(c["document_id"] == "rpi-doc-remote-access-ssh"
               for c in lab.compose("cmd-remote-access-001")["evidence"])


def test_qa_handoff_uses_catalog_product_and_command(lab):
    question = lab.qa_question("cmd-remote-access-004", product_id="raspberry-pi-5")
    assert "Raspberry Pi 5" in question
    assert "ssh learner@raspberrypi.local" in question
