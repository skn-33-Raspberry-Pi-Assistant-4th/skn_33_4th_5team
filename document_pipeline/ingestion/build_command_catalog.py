"""Build the display-only command-lab catalog from the verified v3 manifest."""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "document_pipeline" / "data" / "manifest_v3.json"
DEFAULT_CATALOG = ROOT / "data" / "products" / "command_catalog.json"

TOPICS = {
    "os_installation": ("os-installation", 10),
    "remote_access": ("remote-access", 16),
    "networking": ("networking", 18),
    "camera": ("camera", 16),
    "storage": ("storage", 12),
    "interfaces": ("interfaces", 18),
    "system_status": ("system-status", 10),
}
TOPIC_LABELS = {
    "os_installation": "OS 설치와 초기 설정",
    "remote_access": "원격 접속",
    "networking": "네트워크 연결",
    "camera": "카메라 사용",
    "storage": "저장장치 관리",
    "interfaces": "하드웨어 인터페이스",
    "system_status": "시스템 상태 확인",
}
LEGACY_SEEDS = {
    "sudo raspi-config": "remote_access",
    "sudo touch /boot/firmware/ssh": "remote_access",
    "sudo reboot": "remote_access",
    "ssh learner@raspberrypi.local": "remote_access",
    "ls ~/.ssh": "remote_access",
    "ssh-keygen": "remote_access",
    "ssh-copy-id learner@raspberrypi.local": "remote_access",
    "openssl passwd -6": "os_installation",
}
LEGACY_EVIDENCE_MARKERS = {
    "ssh learner@raspberrypi.local": "ssh <username>@<ip address>",
    "ssh-copy-id learner@raspberrypi.local": "ssh-copy-id <username>@<ip address>",
}
TOKEN = re.compile(r'''(?:<[^<>]+>|"[^"]*"|'[^']*'|[^\s<>"'])+''')
UNSUPPORTED = re.compile(r"(?:&&|\||;|&|\$\(|`)")
DESTRUCTIVE = re.compile(r"(?:^|\s)(?:rm|dd|mkfs|shutdown|halt|poweroff)(?:\s|$)|apt\s+(?:remove|purge)")


def command_lines(content: str) -> list[str]:
    """Return documented one-line shell commands safe for display-only analysis."""

    commands: list[str] = []
    for raw_line in content.splitlines():
        if not raw_line.startswith("$ "):
            continue
        command = raw_line[2:].strip()
        if not command or UNSUPPORTED.search(command) or DESTRUCTIVE.search(command):
            continue
        if command.startswith(("--", "dtoverlay=", "dtparam=", "enable_uart=", "force_turbo=", "core_freq=")):
            continue
        commands.append(command)
    return commands


def root_command(command: str) -> str:
    tokens = TOKEN.findall(command)
    if not tokens:
        return ""
    return tokens[1] if tokens[0] == "sudo" and len(tokens) > 1 else tokens[0]


def candidate_topic(document_id: str, command: str) -> str | None:
    root = root_command(command)
    if document_id == "rpi-doc-camera-rpicam-building" and command in {
        "git clone https://github.com/raspberrypi/rpicam-apps.git",
        "cd rpicam-apps",
        "meson setup build -Denable_libav=enabled -Denable_drm=enabled -Denable_egl=enabled -Denable_qt=enabled -Denable_opencv=disabled -Denable_tflite=disabled -Denable_hailo=disabled",
    }:
        return "os_installation"
    if root.startswith("rpi-keyboard") or root in {"dtoverlay", "systemctl"}:
        return "interfaces"
    if document_id in {"rpi-doc-external-storage", "rpi-doc-boot-nvme"}:
        return "storage"
    if document_id in {
        "rpi-doc-frequency-management",
        "rpi-doc-power-supplies",
        "rpi-doc-config-boot-behaviour",
    } or root in {"vcgencmd", "cat"}:
        return "system_status"
    if document_id == "rpi-doc-networking" or document_id == "rpi-doc-camera-streaming":
        return "networking"
    if document_id in {
        "rpi-doc-remote-access-ssh",
        "rpi-doc-raspberry-pi-connect",
    } or root in {"ssh", "scp", "ssh-keygen", "ssh-add", "ssh-copy-id"}:
        return "remote_access"
    if document_id.startswith("rpi-doc-camera-") and root in {
        "rpicam-hello",
        "rpicam-still",
        "rpicam-vid",
        "meson",
        "ninja",
        "git",
        "cd",
        "ldconfig",
    }:
        return "camera"
    if document_id in {
        "rpi-doc-getting-started-install",
        "rpi-doc-getting-started-setting-up",
        "rpi-doc-config-raspi-config",
    } or root in {"apt", "openssl", "raspi-config", "rpi-imager"}:
        return "os_installation"
    return None


def command_summary(command: str, topic: str) -> str:
    root = root_command(command)
    explanations = {
        "sudo raspi-config": "Raspberry Pi 설정 도구를 엽니다. SSH 활성화는 메뉴에서 별도로 선택합니다.",
        "sudo touch /boot/firmware/ssh": "부팅 파티션에 빈 ssh 파일을 만들어 다음 부팅 시 SSH 활성화를 준비합니다.",
        "sudo reboot": "Raspberry Pi를 재부팅합니다. 접속 중인 SSH 연결은 끊어집니다.",
        "ls ~/.ssh": "현재 사용자 홈의 .ssh 디렉터리 항목을 나열합니다. 파일 내용을 읽지는 않습니다.",
        "openssl passwd -6": "SHA-512 방식의 비밀번호 해시를 생성합니다. 실제 비밀번호를 실험실에 입력하지 마세요.",
        "ssh-keygen": "SSH 인증에 사용할 공개 키와 개인 키 쌍을 생성합니다. 기존 키 경로를 선택할 때 덮어쓰기에 주의합니다.",
        "ssh-copy-id learner@raspberrypi.local": "SSH 접속 대상에 공개 키를 복사해 키 기반 인증을 준비합니다.",
    }
    if command in explanations:
        return explanations[command]
    if root == "ssh":
        return "SSH를 사용해 Raspberry Pi에 원격 접속을 시도하는 명령입니다."
    if root in {"ssh-keygen", "ssh-add", "ssh-copy-id", "scp"}:
        return "SSH 키 기반 원격 접속을 준비하거나 공개 키를 전달하는 명령입니다."
    if root == "nmcli":
        return "NetworkManager의 네트워크 상태를 확인하거나 연결 설정을 다루는 명령입니다."
    if root.startswith("rpicam"):
        return "Raspberry Pi 카메라 앱의 촬영·영상·옵션 동작을 학습하는 명령입니다."
    if root.startswith("rpi-keyboard"):
        return "Raspberry Pi 키보드 컴퓨터의 조명·키 설정을 확인하거나 구성하는 명령입니다."
    if root == "vcgencmd":
        return "Raspberry Pi 펌웨어에서 시스템 상태 값을 조회하는 명령입니다."
    if root in {"lsblk", "blkid", "mount", "umount", "lsof"}:
        return "저장장치의 식별·마운트·사용 상태를 확인하거나 설정하는 명령입니다."
    if root == "apt":
        return "Raspberry Pi OS에서 필요한 패키지를 설치하거나 최신 상태로 준비하는 명령입니다."
    return f"{TOPIC_LABELS[topic]}에 사용하는 공식 명령의 구성과 목적을 학습합니다."


def risk_for(command: str) -> tuple[str, str]:
    root = root_command(command)
    if root in {"ls", "lsblk", "blkid", "lsof", "vcgencmd", "cat", "ffplay", "vlc"} or command.endswith("--version"):
        return "read_only", "조회 결과는 장치·네트워크 상태에 따라 달라질 수 있지만 시스템 설정을 바꾸지는 않습니다."
    if any(value in command for value in ("reboot", "mount ", "umount ", "apt install", "systemctl", "usermod", "nano ", "meson install", "ninja install", "fw-update", "reset-")):
        return "system_change", "실제 실행하면 시스템·장치·서비스 설정이 바뀔 수 있습니다. 이 실험실에서는 실행하지 않습니다."
    return "configuration", "실제 실행하면 연결·카메라·인터페이스 동작이 달라질 수 있습니다. 이 실험실에서는 설명만 제공합니다."


def parts_for(command: str) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    parts: list[dict[str, object]] = []
    fields: list[dict[str, object]] = []
    for index, value in enumerate(TOKEN.findall(command)):
        editable = ("<" in value and ">" in value) or (
            command in LEGACY_SEEDS and value == "learner@raspberrypi.local"
        )
        kind = "option" if value.startswith("-") else "command" if index == 0 or (index == 1 and parts[0]["value"] == "sudo") else "argument"
        part_id = f"part-{index + 1:02d}"
        descriptions = {
            "sudo": "뒤따르는 명령을 관리자 권한으로 요청합니다.",
            "raspi-config": "Raspberry Pi 설정 메뉴를 엽니다.",
            "touch": "파일이 없으면 빈 파일을 만들고, 있으면 타임스탬프를 갱신합니다.",
            "/boot/firmware/ssh": "SSH 활성화를 요청하는 부팅 파티션의 빈 파일 경로입니다.",
            "reboot": "운영체제를 재부팅합니다. 원격 접속이 종료될 수 있습니다.",
            "ssh": "암호화된 원격 로그인 연결을 시작합니다.",
            "learner@raspberrypi.local": "접속할 사용자명과 호스트입니다. 실제 장치 계정과 주소로 바꿉니다.",
            "ls": "디렉터리 항목 이름을 나열합니다.",
            "~/.ssh": "현재 사용자 홈 디렉터리 아래 SSH 설정과 키 저장 위치입니다.",
            "ssh-keygen": "SSH 인증 키 쌍 생성 도구입니다.",
            "ssh-copy-id": "접속 대상 계정에 로컬 공개 키를 등록하는 도구입니다.",
            "openssl": "암호화 도구 모음입니다.",
            "passwd": "비밀번호 해시 생성 하위 명령입니다.",
            "-6": "SHA-512 비밀번호 해시 방식을 선택합니다.",
        }
        parts.append(
            {
                "part_id": part_id,
                "kind": kind,
                "value": value,
                "prefix": "" if index == 0 else " ",
                "label_ko": "입력값" if editable else ("옵션" if kind == "option" else "명령 구성 요소"),
                "description_ko": descriptions.get(value, "사용 환경에 맞게 바꿀 수 있는 예시 입력값입니다." if editable else "명령 구조를 이루는 고정 요소입니다."),
                "editable": editable,
            }
        )
        if editable:
            fields.append(
                {
                    "part_id": part_id,
                    "label_ko": "입력값",
                    "example": value,
                    "validation_pattern": r"^[^\r\n]{1,160}$",
                }
            )
    return parts, fields


def load_legacy_status(path: Path) -> dict[str, dict[str, object]]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {item["canonical_command"]: item for item in payload.get("templates", [])}


def build_catalog(manifest_path: Path, catalog_path: Path) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    legacy = load_legacy_status(catalog_path)
    by_command: dict[str, dict[str, object]] = {}
    for chunk in manifest["chunks"]:
        for command in command_lines(chunk["content"]):
            canonical = " ".join(command.split())
            topic = candidate_topic(chunk["document_id"], canonical)
            if topic and canonical not in by_command:
                by_command[canonical] = {
                    "command": canonical,
                    "topic": topic,
                    "chunk_id": chunk["chunk_id"],
                    "checksum": chunk["chunk_checksum"],
                }
    for command, topic in LEGACY_SEEDS.items():
        if command == "sudo raspi-config":
            matching = next(chunk for chunk in manifest["chunks"]
                            if chunk["document_id"] == "rpi-doc-remote-access-ssh"
                            and "`sudo raspi-config`" in chunk["content"])
            by_command[command] = {"command": command, "topic": topic,
                                  "chunk_id": matching["chunk_id"], "checksum": matching["chunk_checksum"]}
        if command in by_command:
            by_command[command]["topic"] = topic
            continue
        marker = LEGACY_EVIDENCE_MARKERS.get(command, command)
        matching = next((chunk for chunk in manifest["chunks"] if marker in chunk["content"]), None)
        if matching is None:
            raise ValueError(f"legacy command is missing from manifest: {command}")
        by_command[command] = {
            "command": command,
            "topic": topic,
            "chunk_id": matching["chunk_id"],
            "checksum": matching["chunk_checksum"],
        }

    selected: dict[str, list[dict[str, object]]] = defaultdict(list)
    used: set[str] = set()
    for command, topic in LEGACY_SEEDS.items():
        selected[topic].append(by_command[command])
        used.add(command)
    for topic, (_, target) in TOPICS.items():
        pool = [item for item in by_command.values() if item["topic"] == topic and item["command"] not in used]
        pool.sort(key=lambda item: (item["command"].count(" "), item["command"]))
        needed = target - len(selected[topic])
        if len(pool) < needed:
            raise ValueError(f"{topic}: needs {needed} more commands but has only {len(pool)} candidates")
        selected[topic].extend(pool[:needed])
        used.update(item["command"] for item in pool[:needed])

    templates: list[dict[str, object]] = []
    for topic, (id_topic, _) in TOPICS.items():
        for sequence, candidate in enumerate(selected[topic], start=1):
            command = str(candidate["command"])
            parts, fields = parts_for(command)
            legacy_item = legacy.get(command, {})
            risk_level, risk_notice = risk_for(command)
            approved = legacy_item.get("review_status") == "approved"
            templates.append(
                {
                    "template_id": f"cmd-{id_topic}-{sequence:03d}",
                    "topic": topic,
                    "canonical_command": command,
                    "parts": parts,
                    "editable_fields": fields,
                    "execution_context": "Raspberry Pi OS 터미널" if root_command(command) not in {"ssh", "scp", "ffplay", "vlc"} else "Raspberry Pi 또는 연결을 시작하는 PC의 터미널",
                    "effect_ko": command_summary(command, topic),
                    "limitations_ko": "명령의 실제 실행, 장치 연결 상태와 성공 여부는 이 화면에서 확인하지 않습니다.",
                    "default_explanation_ko": command_summary(command, topic),
                    "risk_level": risk_level,
                    "risk_notice_ko": risk_notice,
                    "execution_policy": "display_only",
                    "evidence_ids": [candidate["chunk_id"]],
                    "evidence_checksums": [candidate["checksum"]],
                    "review_status": "approved" if approved else "draft",
                    "reviewed_by": legacy_item.get("reviewed_by") if approved else None,
                    "reviewed_at": legacy_item.get("reviewed_at") if approved else None,
                }
            )
    return {
        "schema_version": "2.0.0",
        "catalog_version": "2026-09-16-command-lab-v2.2",
        "source_manifest": "document_pipeline/data/manifest_v3.json",
        "execution_policy": "display_only",
        "generated_at": datetime.now(UTC).isoformat(),
        "topics": {topic: target for topic, (_, target) in TOPICS.items()},
        "templates": templates,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build PiCare's display-only command catalog.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_CATALOG)
    args = parser.parse_args()
    payload = build_catalog(args.manifest, args.output)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(payload['templates'])} command templates to {args.output}")


if __name__ == "__main__":
    main()
