from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .agents import AgentContext, build_agent
from .defaults import DEFAULT_LLM_PROFILES, DEFAULT_MEMORIES, DEFAULT_PARTICIPANTS, DEFAULT_ROOM, DEFAULT_TOOLS
from .models import (
    LLMProfile,
    MemoryNote,
    MeetingPhase,
    Message,
    MessageKind,
    Participant,
    ParticipantType,
    ReviewDecision,
    RoomState,
    RoomStatus,
    RoomSummary,
    TaskItem,
    TaskStatus,
    ToolDefinition,
)
from .persistence import Database, now_iso
from .role_store import RoleConfigStore
from .tooling import build_tool_definitions


class MeetingRoomService:
    """会议室主服务：负责多会议室、角色配置、讨论推进和持久化。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db = Database(db_path)
        self.db.initialize()
        self.role_store = RoleConfigStore(Path(db_path).parent / "rooms")
        self._seed_defaults_if_needed()

    def _seed_defaults_if_needed(self) -> None:
        if not self.db.query_one("SELECT profile_id FROM llm_profiles LIMIT 1"):
            now = now_iso()
            self.db.insert_many(
                "llm_profiles",
                [
                    {
                        **profile,
                        "enable_thinking": 1 if profile["enable_thinking"] else 0,
                        "is_default": 1 if profile["is_default"] else 0,
                        "created_at": now,
                        "updated_at": now,
                    }
                    for profile in DEFAULT_LLM_PROFILES
                ],
            )

        if not self.db.query_one("SELECT room_id FROM rooms LIMIT 1"):
            room = self.create_room(DEFAULT_ROOM["room_name"], DEFAULT_ROOM["goal"], seed_defaults=True)
            self.add_system_message(room.room_id, f"会议室已创建，目标：{room.goal}")
            for memory in DEFAULT_MEMORIES:
                self.add_memory(room.room_id, memory["title"], memory["content"], memory["tags"], memory["source"])

    def list_rooms(self) -> list[RoomSummary]:
        rows = self.db.query_all("SELECT * FROM rooms ORDER BY updated_at DESC, created_at DESC")
        return [
            RoomSummary(
                room_id=row["room_id"],
                room_name=row["room_name"],
                goal=row["goal"],
                phase=MeetingPhase(row["phase"]),
                status=RoomStatus(row["status"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )
            for row in rows
        ]

    def create_room(self, room_name: str, goal: str, seed_defaults: bool = False) -> RoomSummary:
        room_id = f"room-{uuid4().hex[:8]}"
        now = now_iso()
        self.db.execute(
            "INSERT INTO rooms (room_id, room_name, goal, phase, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (room_id, room_name.strip(), goal.strip(), MeetingPhase.DISCOVERY.value, RoomStatus.ACTIVE.value, now, now),
        )
        participants = self._seed_participants() if seed_defaults else [self._default_moderator()]
        self.role_store.save_roles(room_id, participants)
        self.role_store.workspace_dir(room_id)
        return self.get_room(room_id)

    def get_room(self, room_id: str) -> RoomSummary:
        row = self.db.query_one("SELECT * FROM rooms WHERE room_id = ?", (room_id,))
        if row is None:
            raise ValueError(f"Unknown room: {room_id}")
        return RoomSummary(
            room_id=row["room_id"],
            room_name=row["room_name"],
            goal=row["goal"],
            phase=MeetingPhase(row["phase"]),
            status=RoomStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def get_state(self, room_id: str) -> RoomState:
        room = self.get_room(room_id)
        return RoomState(
            room_id=room.room_id,
            room_name=room.room_name,
            goal=room.goal,
            phase=room.phase,
            status=room.status,
            participants=self.list_participants(room_id),
            messages=self.list_messages(room_id),
            tasks=self.list_tasks(room_id),
            decisions=self.list_decisions(room_id),
        )

    def update_room(self, room_id: str, room_name: str, goal: str) -> None:
        self.db.execute(
            "UPDATE rooms SET room_name = ?, goal = ?, updated_at = ? WHERE room_id = ?",
            (room_name.strip(), goal.strip(), now_iso(), room_id),
        )

    def add_participant(
        self,
        room_id: str,
        name: str,
        role: str,
        participant_type: ParticipantType,
        description: str = "",
        llm_profile_id: str = "",
        tools: list[str] | None = None,
        system_prompt: str = "",
        participant_id: str | None = None,
    ) -> Participant:
        participant = Participant(
            participant_id=participant_id or self._next_participant_id(room_id),
            name=name.strip(),
            role=role.strip(),
            participant_type=participant_type,
            description=description.strip(),
            llm_profile_id=llm_profile_id.strip(),
            tools=list(tools or []),
            system_prompt=system_prompt.strip(),
        )
        self.role_store.upsert_role(room_id, participant)
        return participant

    def save_role(self, room_id: str, participant: Participant) -> None:
        self.role_store.upsert_role(room_id, participant)

    def get_role(self, room_id: str, participant_id: str) -> Participant:
        participant = self.role_store.get_role(room_id, participant_id)
        if participant is None:
            raise ValueError(f"Unknown participant: {participant_id}")
        return participant

    def add_system_message(self, room_id: str, content: str, kind: MessageKind = MessageKind.SYSTEM) -> Message:
        message = Message(
            sender_name="System",
            sender_role="System",
            sender_id="system",
            content=content,
            kind=kind,
        )
        self.db.execute(
            "INSERT INTO messages (room_id, sender_id, sender_name, sender_role, content, kind, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                room_id,
                message.sender_id,
                message.sender_name,
                message.sender_role,
                message.content,
                message.kind.value,
                message.created_at.isoformat(timespec="seconds"),
            ),
        )
        return message

    def post_message(self, room_id: str, sender_id: str, content: str) -> Message:
        participant = self.get_participant(room_id, sender_id)
        self._handle_host_command(room_id, participant, content)
        message = Message(
            sender_name=participant.name,
            sender_role=participant.role,
            sender_id=participant.participant_id,
            content=content.strip(),
            kind=MessageKind.CHAT,
        )
        self.db.execute(
            "INSERT INTO messages (room_id, sender_id, sender_name, sender_role, content, kind, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                room_id,
                message.sender_id,
                message.sender_name,
                message.sender_role,
                message.content,
                message.kind.value,
                message.created_at.isoformat(timespec="seconds"),
            ),
        )
        self._touch_room(room_id)
        self._advance_phase_for_chat(room_id)
        return message

    def trigger_ai_discussion(self, room_id: str, latest_message: Message | None = None, max_rounds: int = 4) -> list[Message]:
        """每个 Agent 在独立线程中思考，若相关则回复，并继续多轮讨论。"""

        state = self.get_state(room_id)
        if state.status is not RoomStatus.ACTIVE:
            return []

        generated_messages: list[Message] = []
        trigger_message = latest_message or (state.messages[-1] if state.messages else None)
        for _ in range(max_rounds):
            batch = self._run_one_discussion_round(room_id, trigger_message)
            if not batch:
                break
            generated_messages.extend(batch)
            trigger_message = batch[-1]
            refreshed = self.get_state(room_id)
            if refreshed.status is not RoomStatus.ACTIVE:
                break
        return generated_messages

    def _run_one_discussion_round(self, room_id: str, latest_message: Message | None) -> list[Message]:
        state = self.get_state(room_id)
        recent_messages = state.messages[-12:]
        prompt_message = latest_message or (recent_messages[-1] if recent_messages else None)
        relevant_memories = self.search_memories(room_id, prompt_message.content if prompt_message else state.goal)
        context = AgentContext(
            room_id=state.room_id,
            room_name=state.room_name,
            room_goal=state.goal,
            room_status=state.status,
            latest_message=prompt_message,
            tasks=state.tasks,
            recent_messages=recent_messages,
            memories=relevant_memories,
            workspace_dir=self.role_store.workspace_dir(room_id),
        )
        profiles = {profile.profile_id: profile for profile in self.list_llm_profiles()}
        ai_participants = [item for item in state.participants if item.participant_type is ParticipantType.AI and item.enabled]
        generated_messages: list[Message] = []

        with ThreadPoolExecutor(max_workers=max(1, len(ai_participants))) as executor:
            futures = [
                executor.submit(self._build_agent_reply, room_id, participant, profiles.get(participant.llm_profile_id) or self.get_default_profile(), context)
                for participant in ai_participants
            ]
            for future in futures:
                message = future.result()
                if message is not None:
                    generated_messages.append(message)

        for message in generated_messages:
            self.db.execute(
                "INSERT INTO messages (room_id, sender_id, sender_name, sender_role, content, kind, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    room_id,
                    message.sender_id,
                    message.sender_name,
                    message.sender_role,
                    message.content,
                    message.kind.value,
                    message.created_at.isoformat(timespec="seconds"),
                ),
            )

        if generated_messages:
            self._touch_room(room_id)
            self._advance_phase_for_chat(room_id)
        return generated_messages

    def _build_agent_reply(
        self,
        room_id: str,
        participant: Participant,
        profile: LLMProfile | None,
        context: AgentContext,
    ) -> Message | None:
        _ = room_id
        agent = build_agent(participant, profile)
        if not agent.should_reply(context):
            return None
        reply_text = agent.generate_reply(context).strip()
        if not reply_text:
            return None
        return Message(
            sender_id=participant.participant_id,
            sender_name=participant.name,
            sender_role=participant.role,
            content=reply_text,
            kind=MessageKind.CHAT,
        )

    def add_task(self, room_id: str, title: str, description: str, owner_id: str, acceptance_criteria: str) -> TaskItem:
        owner = self.get_participant(room_id, owner_id)
        now = datetime.now()
        task = TaskItem(
            task_id=self._next_task_id(room_id),
            title=title.strip(),
            description=description.strip(),
            owner_id=owner.participant_id,
            owner_name=owner.name,
            acceptance_criteria=acceptance_criteria.strip(),
            created_at=now,
            updated_at=now,
        )
        self.db.execute(
            """
            INSERT INTO tasks (
                task_id, room_id, title, description, owner_id, owner_name, acceptance_criteria, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task.task_id,
                room_id,
                task.title,
                task.description,
                task.owner_id,
                task.owner_name,
                task.acceptance_criteria,
                task.status.value,
                task.created_at.isoformat(timespec="seconds"),
                task.updated_at.isoformat(timespec="seconds"),
            ),
        )
        if self.get_state(room_id).phase == MeetingPhase.DISCOVERY:
            self._set_phase(room_id, MeetingPhase.EXECUTION)
        self.add_system_message(room_id, f"任务已创建：{task.title}，负责人：{task.owner_name}")
        return task

    def update_task_status(self, room_id: str, task_id: str, status: TaskStatus) -> TaskItem:
        task = self.get_task(room_id, task_id)
        task.status = status
        task.updated_at = datetime.now()
        self.db.execute(
            "UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ? AND room_id = ?",
            (status.value, task.updated_at.isoformat(timespec="seconds"), task.task_id, room_id),
        )
        self._update_phase_for_tasks(room_id)
        self.add_system_message(room_id, f"任务状态更新：{task.title} -> {status.value}")
        return task

    def record_review(self, room_id: str, approved: bool, reviewer_name: str, note: str) -> ReviewDecision:
        decision = ReviewDecision(approved=approved, reviewer_name=reviewer_name.strip(), note=note.strip())
        self.db.execute(
            "INSERT INTO decisions (room_id, approved, reviewer_name, note, created_at) VALUES (?, ?, ?, ?, ?)",
            (room_id, 1 if decision.approved else 0, decision.reviewer_name, decision.note, decision.created_at.isoformat(timespec="seconds")),
        )
        if approved:
            if self._all_tasks_closed(room_id):
                self._set_phase(room_id, MeetingPhase.COMPLETED)
            else:
                self._set_phase(room_id, MeetingPhase.REVIEW)
            message = f"评审通过，评审人：{reviewer_name}。说明：{note}"
        else:
            self._set_phase(room_id, MeetingPhase.EXECUTION)
            message = f"评审未通过，评审人：{reviewer_name}。需要修正：{note}"
        self.add_system_message(room_id, message, kind=MessageKind.REVIEW)
        self.add_memory(
            room_id=room_id,
            title=f"评审记录-{reviewer_name}",
            content=message,
            tags="review,decision",
            source="review",
        )
        return decision

    def add_memory(self, room_id: str, title: str, content: str, tags: str = "", source: str = "manual") -> MemoryNote:
        memory = MemoryNote(title=title.strip(), content=content.strip(), tags=tags.strip(), source=source.strip() or "manual")
        self.db.execute(
            "INSERT INTO memories (room_id, title, content, tags, source, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                room_id,
                memory.title,
                memory.content,
                memory.tags,
                memory.source,
                memory.created_at.isoformat(timespec="seconds"),
                memory.updated_at.isoformat(timespec="seconds"),
            ),
        )
        return memory

    def search_memories(self, room_id: str, query_text: str, limit: int = 6) -> list[MemoryNote]:
        query_terms = self._build_search_terms(query_text)
        memories = self.list_memories(room_id, limit=60)
        if not query_terms:
            return memories[:limit]

        def score(memory: MemoryNote) -> tuple[int, str]:
            haystack = f"{memory.title} {memory.content} {memory.tags}".lower()
            hits = sum(1 for term in query_terms if term in haystack)
            return (hits, memory.updated_at.isoformat(timespec="seconds"))

        ranked = sorted(memories, key=score, reverse=True)
        return [memory for memory in ranked if score(memory)[0] > 0][:limit] or memories[:limit]

    def list_participants(self, room_id: str) -> list[Participant]:
        return self.role_store.load_roles(room_id)

    def list_messages(self, room_id: str, limit: int = 300) -> list[Message]:
        rows = self.db.query_all(
            "SELECT * FROM messages WHERE room_id = ? ORDER BY message_id DESC LIMIT ?",
            (room_id, limit),
        )
        return [self._row_to_message(row) for row in reversed(rows)]

    def list_tasks(self, room_id: str) -> list[TaskItem]:
        rows = self.db.query_all("SELECT * FROM tasks WHERE room_id = ? ORDER BY updated_at DESC, created_at DESC", (room_id,))
        return [
            TaskItem(
                task_id=row["task_id"],
                title=row["title"],
                description=row["description"],
                owner_id=row["owner_id"],
                owner_name=row["owner_name"],
                acceptance_criteria=row["acceptance_criteria"],
                status=TaskStatus(row["status"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )
            for row in rows
        ]

    def list_decisions(self, room_id: str) -> list[ReviewDecision]:
        rows = self.db.query_all("SELECT * FROM decisions WHERE room_id = ? ORDER BY decision_id DESC LIMIT 50", (room_id,))
        return [
            ReviewDecision(
                decision_id=row["decision_id"],
                approved=bool(row["approved"]),
                reviewer_name=row["reviewer_name"],
                note=row["note"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def list_memories(self, room_id: str, limit: int = 30) -> list[MemoryNote]:
        rows = self.db.query_all("SELECT * FROM memories WHERE room_id = ? ORDER BY updated_at DESC LIMIT ?", (room_id, limit))
        return [
            MemoryNote(
                memory_id=row["memory_id"],
                title=row["title"],
                content=row["content"],
                tags=row["tags"],
                source=row["source"],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )
            for row in rows
        ]

    def list_llm_profiles(self) -> list[LLMProfile]:
        rows = self.db.query_all("SELECT * FROM llm_profiles ORDER BY profile_id")
        return [
            LLMProfile(
                profile_id=row["profile_id"],
                name=row["name"],
                provider=row["provider"],
                model=row["model"],
                base_url=row["base_url"],
                api_key=row["api_key"],
                temperature=float(row["temperature"]),
                max_tokens=int(row["max_tokens"]),
                enable_thinking=bool(row["enable_thinking"]),
                is_default=bool(row["is_default"]),
            )
            for row in rows
        ]

    def save_llm_profile(
        self,
        profile_id: str,
        name: str,
        provider: str,
        model: str,
        base_url: str,
        api_key: str,
        temperature: float,
        max_tokens: int,
        enable_thinking: bool,
        is_default: bool,
    ) -> None:
        now = now_iso()
        if is_default:
            self.db.execute("UPDATE llm_profiles SET is_default = 0")
        self.db.execute(
            """
            INSERT INTO llm_profiles (
                profile_id, name, provider, model, base_url, api_key, temperature, max_tokens,
                enable_thinking, is_default, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(profile_id) DO UPDATE SET
                name = excluded.name,
                provider = excluded.provider,
                model = excluded.model,
                base_url = excluded.base_url,
                api_key = excluded.api_key,
                temperature = excluded.temperature,
                max_tokens = excluded.max_tokens,
                enable_thinking = excluded.enable_thinking,
                is_default = excluded.is_default,
                updated_at = excluded.updated_at
            """,
            (
                profile_id.strip(),
                name.strip(),
                provider.strip(),
                model.strip(),
                base_url.strip(),
                api_key.strip(),
                temperature,
                max_tokens,
                1 if enable_thinking else 0,
                1 if is_default else 0,
                now,
                now,
            ),
        )

    def get_default_profile(self) -> LLMProfile | None:
        row = self.db.query_one("SELECT * FROM llm_profiles WHERE is_default = 1 ORDER BY profile_id LIMIT 1")
        if row is None:
            profiles = self.list_llm_profiles()
            return profiles[0] if profiles else None
        return LLMProfile(
            profile_id=row["profile_id"],
            name=row["name"],
            provider=row["provider"],
            model=row["model"],
            base_url=row["base_url"],
            api_key=row["api_key"],
            temperature=float(row["temperature"]),
            max_tokens=int(row["max_tokens"]),
            enable_thinking=bool(row["enable_thinking"]),
            is_default=bool(row["is_default"]),
        )

    def get_participant(self, room_id: str, participant_id: str) -> Participant:
        for participant in self.list_participants(room_id):
            if participant.participant_id == participant_id:
                return participant
        raise ValueError(f"Unknown participant: {participant_id}")

    def get_task(self, room_id: str, task_id: str) -> TaskItem:
        for task in self.list_tasks(room_id):
            if task.task_id == task_id:
                return task
        raise ValueError(f"Unknown task: {task_id}")

    def change_room_status(self, room_id: str, status: RoomStatus) -> None:
        self.db.execute("UPDATE rooms SET status = ?, updated_at = ? WHERE room_id = ?", (status.value, now_iso(), room_id))
        self.add_system_message(room_id, f"会议室状态已切换为：{status.value}")

    def list_tools(self) -> list[ToolDefinition]:
        return build_tool_definitions(DEFAULT_TOOLS)

    def _advance_phase_for_chat(self, room_id: str) -> None:
        state = self.get_state(room_id)
        if state.phase == MeetingPhase.DISCOVERY and len(state.messages) >= 3:
            self._set_phase(room_id, MeetingPhase.PLANNING)

    def _update_phase_for_tasks(self, room_id: str) -> None:
        # 任务状态会驱动会议室的全局阶段。
        tasks = self.list_tasks(room_id)
        if not tasks:
            return
        if any(task.status in {TaskStatus.IN_PROGRESS, TaskStatus.PENDING, TaskStatus.REJECTED} for task in tasks):
            self._set_phase(room_id, MeetingPhase.EXECUTION)
            return
        if any(task.status == TaskStatus.AWAITING_REVIEW for task in tasks):
            self._set_phase(room_id, MeetingPhase.REVIEW)
            return
        if self._all_tasks_closed(room_id):
            self._set_phase(room_id, MeetingPhase.COMPLETED)

    def _all_tasks_closed(self, room_id: str) -> bool:
        tasks = self.list_tasks(room_id)
        return bool(tasks) and all(task.status in {TaskStatus.APPROVED, TaskStatus.DONE} for task in tasks)

    def _set_phase(self, room_id: str, phase: MeetingPhase) -> None:
        self.db.execute("UPDATE rooms SET phase = ?, updated_at = ? WHERE room_id = ?", (phase.value, now_iso(), room_id))

    def _touch_room(self, room_id: str) -> None:
        self.db.execute("UPDATE rooms SET updated_at = ? WHERE room_id = ?", (now_iso(), room_id))

    def _next_participant_id(self, room_id: str) -> str:
        rows = self.list_participants(room_id)
        max_number = max((int(item.participant_id[1:]) for item in rows if item.participant_id.startswith("p")), default=0)
        return f"p{max_number + 1}"

    def _next_task_id(self, room_id: str) -> str:
        rows = self.list_tasks(room_id)
        max_number = max((int(item.task_id[1:]) for item in rows if item.task_id.startswith("t")), default=0)
        return f"t{max_number + 1}"

    def _seed_participants(self) -> list[Participant]:
        return [
            Participant(
                participant_id=item["participant_id"],
                name=item["name"],
                role=item["role"],
                participant_type=ParticipantType(item["participant_type"]),
                description=item["description"],
                enabled=bool(item["enabled"]),
                llm_profile_id=item["llm_profile_id"],
                tools=list(item.get("tools", [])),
                system_prompt=item.get("system_prompt", ""),
            )
            for item in DEFAULT_PARTICIPANTS
        ]

    def _default_moderator(self) -> Participant:
        moderator = DEFAULT_PARTICIPANTS[0]
        return Participant(
            participant_id=moderator["participant_id"],
            name=moderator["name"],
            role=moderator["role"],
            participant_type=ParticipantType(moderator["participant_type"]),
            description=moderator["description"],
            enabled=bool(moderator["enabled"]),
            llm_profile_id=moderator["llm_profile_id"],
            tools=list(moderator.get("tools", [])),
            system_prompt=moderator.get("system_prompt", ""),
        )

    def _handle_host_command(self, room_id: str, participant: Participant, content: str) -> None:
        if participant.participant_type is not ParticipantType.HUMAN:
            return
        if "主持人" not in participant.role and "主持人" not in participant.name:
            return
        if "停止讨论" in content:
            self.change_room_status(room_id, RoomStatus.STOPPED)
        elif "暂停讨论" in content:
            self.change_room_status(room_id, RoomStatus.PAUSED)
        elif "继续讨论" in content or "恢复讨论" in content:
            self.change_room_status(room_id, RoomStatus.ACTIVE)

    def _row_to_message(self, row: object) -> Message:
        return Message(
            message_id=row["message_id"],
            sender_id=row["sender_id"],
            sender_name=row["sender_name"],
            sender_role=row["sender_role"],
            content=row["content"],
            kind=MessageKind(row["kind"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def _build_search_terms(self, query_text: str) -> list[str]:
        normalized = query_text.strip().lower()
        terms = {term for term in normalized.split() if len(term) >= 2}
        if len(normalized) >= 2:
            terms.add(normalized)
            terms.update(normalized[index : index + 2] for index in range(len(normalized) - 1))
            terms.update(normalized[index : index + 3] for index in range(len(normalized) - 2))
        return sorted(term for term in terms if term.strip())