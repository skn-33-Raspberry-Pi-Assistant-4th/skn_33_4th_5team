from copy import deepcopy
import shlex

import pytest

from document_pipeline.ingestion.build_command_catalog import parts_for
from src.services.command_lab_service import CommandLabError, CommandLabService


@pytest.fixture
def lab():
    return CommandLabService()


def test_approved_only_and_audit(lab):
    audit = lab.audit()
    assert audit == {"total": 100, "approved": 100, "draft": 0, "errors": []}
    assert audit["errors"] == []
    assert len(lab.list_templates()) == 100


def test_every_approved_command_roundtrip(lab):
    for item in lab.list_templates():
        result = lab.analyze(item["canonical_command"])
        assert result["command"] == item["canonical_command"]
        assert result["execution_policy"] == "display_only"
        assert result["evidence"]


def test_all_topics_are_available_after_final_review(lab):
    assert {topic: len(lab.list_templates(topic=topic)) for topic in (
        "os_installation", "remote_access", "networking", "camera", "storage", "interfaces", "system_status"
    )} == {
        "os_installation": 10,
        "remote_access": 16,
        "networking": 18,
        "camera": 16,
        "storage": 12,
        "interfaces": 18,
        "system_status": 10,
    }


def test_analyze_keeps_editable_protocol_templates_distinct(lab):
    tcp = lab.compose("cmd-networking-002", {"part-02": "tcp://camera.local:9000"})
    assert tcp["command"] == "vlc tcp://camera.local:9000"
    assert lab.analyze(tcp["command"])["template_id"] == "cmd-networking-002"

    with pytest.raises(CommandLabError, match="예시 구조"):
        lab.compose("cmd-networking-002", {"part-02": "rtsp://camera.local:8554/stream1"})
    with pytest.raises(CommandLabError, match="예시 구조"):
        lab.compose("cmd-networking-002", {"part-02": "tcp://camera.local:not-a-port"})


def test_ssid_placeholder_supports_a_quoted_space_without_changing_template(lab):
    result = lab.compose("cmd-networking-008", {"part-06": "Home WiFi"})
    assert result["command"] == "sudo nmcli dev wifi connect 'Home WiFi'"
    analyzed = lab.analyze(result["command"])
    assert analyzed["template_id"] == "cmd-networking-008"
    assert analyzed["values"] == {"part-06": "Home WiFi"}


def test_edit_ssh_and_analyze_roundtrip(lab):
    result = lab.compose("cmd-remote-access-004", {"part-02": "pi@192.168.0.12"}, product_id="raspberry-pi-5")
    assert result["command"] == "ssh pi@192.168.0.12"
    assert result["product"]["name"] == "Raspberry Pi 5"
    assert lab.analyze(result["command"])["values"] == {"part-02": "pi@192.168.0.12"}


def test_official_and_user_changed_values_have_distinct_validation_states(lab):
    official = lab.compose("cmd-remote-access-004")
    assert official["validation_summary"]["status"] == "valid"
    assert official["field_validation"][0]["changed"] is False
    assert official["parts"][1]["changed"] is False

    changed = lab.compose("cmd-remote-access-004", {"part-02": "pi@raspberrypi.local"})
    assert changed["validation_summary"]["status"] == "warning"
    assert "실행 성공은 확인되지 않았습니다" in changed["validation_summary"]["message"]
    assert changed["field_validation"][0]["changed"] is True
    assert changed["parts"][1]["changed"] is True


@pytest.mark.parametrize("target", ["pi@192.168.0.12", "pi@raspberrypi.local", "pi@[2001:db8::1]"])
def test_valid_ip_hostname_and_ipv6_ssh_targets_pass(lab, target):
    assert shlex.split(lab.compose("cmd-remote-access-004", {"part-02": target})["command"])[1] == target


@pytest.mark.parametrize(
    ("target", "message"),
    [
        ("pi@999.999.999.999", "0~255"),
        ("pi@-camera.local", "하이픈"),
        ("pi@camera_.local", "호스트 이름"),
        ("9pi@camera.local", "사용자명"),
    ],
)
def test_invalid_ip_hostname_and_username_are_rejected_with_specific_messages(lab, target, message):
    with pytest.raises(CommandLabError, match=message):
        lab.compose("cmd-remote-access-004", {"part-02": target})


@pytest.mark.parametrize("port", [1, 65535])
def test_valid_port_boundaries_pass(lab, port):
    result = lab.compose("cmd-networking-002", {"part-02": f"tcp://camera.local:{port}"})
    assert result["validation_summary"]["status"] == "warning"


@pytest.mark.parametrize("port", [0, 65536, 99999])
def test_invalid_port_boundaries_are_rejected(lab, port):
    with pytest.raises(CommandLabError, match="1~65535"):
        lab.compose("cmd-networking-002", {"part-02": f"tcp://camera.local:{port}"})


def test_invalid_stream_host_is_rejected(lab):
    with pytest.raises(CommandLabError, match="0~255"):
        lab.compose("cmd-networking-002", {"part-02": "tcp://999.999.999.999:8554"})
    with pytest.raises(CommandLabError, match="1~65535"):
        lab.analyze("vlc tcp://camera.local:99999")


def test_ssid_uses_utf8_byte_limit(lab):
    assert lab.compose("cmd-networking-008", {"part-06": "a" * 32})["command"] == f"sudo nmcli dev wifi connect {'a' * 32}"
    with pytest.raises(CommandLabError, match="32바이트"):
        lab.compose("cmd-networking-008", {"part-06": "가" * 11})


def test_keyboard_coordinates_and_tga_path_are_validated(lab):
    result = lab.compose("cmd-interfaces-016", {"part-04": "0", "part-05": "12"})
    assert result["command"] == "rpi-keyboard-config key get 0 12"
    with pytest.raises(CommandLabError, match="0 이상의 정수"):
        lab.compose("cmd-interfaces-016", {"part-04": "row", "part-05": "1"})
    with pytest.raises(CommandLabError, match=".tga"):
        lab.compose("cmd-system-status-004", {"part-03": "splash.png"})
    with pytest.raises(CommandLabError, match="상위 경로"):
        lab.compose("cmd-system-status-004", {"part-03": "../splash.tga"})


def test_quoted_stream_template_keeps_expected_shell_shape(lab):
    value = '"tcp://camera.local:9000?listen=1"'
    result = lab.compose("cmd-networking-017", {"part-10": value})
    assert result["command"].endswith(f"-o {value}")


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
