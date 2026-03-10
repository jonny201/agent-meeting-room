from __future__ import annotations

import json
from pathlib import Path

from .models import Participant, ParticipantType


class RoleConfigStore:
    """使用 JSON 文件保存每个会议室的角色配置。"""

    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def room_dir(self, room_id: str) -> Path:
        room_dir = self.base_dir / room_id
        room_dir.mkdir(parents=True, exist_ok=True)
        return room_dir

    def workspace_dir(self, room_id: str) -> Path:
        workspace_dir = self.room_dir(room_id) / "workspace"
        workspace_dir.mkdir(parents=True, exist_ok=True)
        return workspace_dir

    def roles_file(self, room_id: str) -> Path:
        return self.room_dir(room_id) / "roles.json"

    def save_roles(self, room_id: str, participants: list[Participant]) -> None:
        payload = {
            "room_id": room_id,
            "participants": [self._participant_to_dict(participant) for participant in participants],
        }
        self.roles_file(room_id).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_roles(self, room_id: str) -> list[Participant]:
        roles_path = self.roles_file(room_id)
        if not roles_path.exists():
            return []
        payload = json.loads(roles_path.read_text(encoding="utf-8"))
        return [self._participant_from_dict(item) for item in payload.get("participants", [])]

    def get_role(self, room_id: str, participant_id: str) -> Participant | None:
        for participant in self.load_roles(room_id):
            if participant.participant_id == participant_id:
                return participant
        return None

    def upsert_role(self, room_id: str, participant: Participant) -> None:
        participants = self.load_roles(room_id)
        updated = False
        for index, existing in enumerate(participants):
            if existing.participant_id == participant.participant_id:
                participants[index] = participant
                updated = True
                break
        if not updated:
            participants.append(participant)
        self.save_roles(room_id, participants)

    def _participant_to_dict(self, participant: Participant) -> dict[str, object]:
        return {
            "participant_id": participant.participant_id,
            "name": participant.name,
            "role": participant.role,
            "participant_type": participant.participant_type.value,
            "description": participant.description,
            "enabled": participant.enabled,
            "llm_profile_id": participant.llm_profile_id,
            "tools": participant.tools,
            "system_prompt": participant.system_prompt,
        }

    def _participant_from_dict(self, payload: dict[str, object]) -> Participant:
        return Participant(
            participant_id=str(payload.get("participant_id", "")),
            name=str(payload.get("name", "")),
            role=str(payload.get("role", "")),
            participant_type=ParticipantType(str(payload.get("participant_type", ParticipantType.HUMAN.value))),
            description=str(payload.get("description", "")),
            enabled=bool(payload.get("enabled", True)),
            llm_profile_id=str(payload.get("llm_profile_id", "")),
            tools=[str(item) for item in payload.get("tools", [])],
            system_prompt=str(payload.get("system_prompt", "")),
        )