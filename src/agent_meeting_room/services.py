from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .agents import AgentContext, AgentTurn, build_agent
from .defaults import DEFAULT_LLM_PROFILES, DEFAULT_MEMORIES, DEFAULT_PARTICIPANTS, DEFAULT_ROLE_TEMPLATES, DEFAULT_ROOM, DEFAULT_TOOLS
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

    def trigger_ai_discussion(self, room_id: str, latest_message: Message | None = None, max_rounds: int = 10) -> list[Message]:
        """按接力模式推进讨论：由上一位 Agent 推荐下一位 Agent。"""

        state = self.get_state(room_id)
        if state.status is not RoomStatus.ACTIVE:
            return []

        generated_messages: list[Message] = []
        trigger_message = latest_message or (state.messages[-1] if state.messages else None)
        next_participant_id: str | None = None
        visit_counts: dict[str, int] = {}
        for _ in range(max_rounds):
            batch, next_participant_id, requires_moderator = self._run_one_discussion_round(
                room_id,
                trigger_message,
                next_participant_id,
                visit_counts,
            )
            if not batch:
                break
            generated_messages.extend(batch)
            trigger_message = batch[-1]
            if trigger_message.sender_id != "system":
                visit_counts[trigger_message.sender_id] = visit_counts.get(trigger_message.sender_id, 0) + 1
            refreshed = self.get_state(room_id)
            if requires_moderator:
                generated_messages.append(self.add_system_message(room_id, "所有 Agent 当前都认为链路已基本闭环，请主持人决定继续讨论还是结束。"))
                break
            if refreshed.status is not RoomStatus.ACTIVE or next_participant_id is None:
                break
        return generated_messages

    def drive_room_to_completion(self, room_id: str, latest_message: Message | None = None, max_cycles: int = 8) -> list[Message]:
        generated_messages: list[Message] = []
        trigger_message = latest_message or (self.list_messages(room_id)[-1] if self.list_messages(room_id) else None)
        for _ in range(max_cycles):
            batch = self.trigger_ai_discussion(room_id, trigger_message, max_rounds=12)
            if batch:
                generated_messages.extend(batch)
            state = self.get_state(room_id)
            if state.status is not RoomStatus.ACTIVE or self._all_tasks_closed(room_id):
                break
            if batch:
                trigger_message = next((message for message in reversed(batch) if message.sender_id != "system"), batch[-1])
                if batch[-1].sender_id == "system":
                    trigger_message = self.add_system_message(room_id, self._build_task_followup_message(room_id))
                    generated_messages.append(trigger_message)
            else:
                if not state.tasks:
                    break
                trigger_message = self.add_system_message(room_id, self._build_task_followup_message(room_id))
                generated_messages.append(trigger_message)
        return generated_messages

    def _run_one_discussion_round(
        self,
        room_id: str,
        latest_message: Message | None,
        next_participant_id: str | None,
        visit_counts: dict[str, int],
    ) -> tuple[list[Message], str | None, bool]:
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
            participants=state.participants,
            workspace_dir=self.role_store.workspace_dir(room_id),
        )
        profiles = {profile.profile_id: profile for profile in self.list_llm_profiles()}
        ai_participants = [item for item in state.participants if item.participant_type is ParticipantType.AI and item.enabled]
        participant = self._select_next_participant(ai_participants, context, next_participant_id, visit_counts)
        if participant is None:
            return [], None, True

        built = self._build_agent_turn(
            room_id,
            participant,
            profiles.get(participant.llm_profile_id) or self.get_default_profile(),
            context,
        )
        if built is None:
            return [], None, True

        message, turn = built
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
        self._auto_progress_tasks(room_id, participant, turn)
        resolved_next = self._resolve_handoff_target(ai_participants, turn.next_agent_hint, participant.participant_id, visit_counts)
        if turn.requires_moderator:
            return [message], None, True
        return [message], resolved_next, False

    def _build_agent_turn(
        self,
        room_id: str,
        participant: Participant,
        profile: LLMProfile | None,
        context: AgentContext,
    ) -> tuple[Message, AgentTurn] | None:
        _ = room_id
        agent = build_agent(participant, profile)
        if not agent.should_reply(context):
            return None
        turn = agent.plan_turn(context)
        if not turn.reply_text.strip():
            return None
        return (
            Message(
                sender_id=participant.participant_id,
                sender_name=participant.name,
                sender_role=participant.role,
                content=turn.reply_text.strip(),
                kind=MessageKind.CHAT,
            ),
            turn,
        )

    def _select_next_participant(
        self,
        ai_participants: list[Participant],
        context: AgentContext,
        next_participant_id: str | None,
        visit_counts: dict[str, int],
    ) -> Participant | None:
        if next_participant_id:
            for participant in ai_participants:
                if participant.participant_id == next_participant_id and visit_counts.get(participant.participant_id, 0) < 2:
                    return participant

        scored_candidates: list[tuple[int, Participant]] = []
        for participant in ai_participants:
            agent = build_agent(participant, self.get_default_profile())
            if not agent.should_reply(context):
                continue
            score = self._score_participant_for_context(participant, context)
            if visit_counts.get(participant.participant_id, 0) >= 2:
                score -= 50
            scored_candidates.append((score, participant))

        if not scored_candidates:
            return None
        scored_candidates.sort(key=lambda item: item[0], reverse=True)
        return scored_candidates[0][1]

    def _score_participant_for_context(self, participant: Participant, context: AgentContext) -> int:
        latest_text = context.latest_message.content.lower() if context.latest_message else ""
        role_name = participant.role.lower()
        score = len(participant.tools)
        if participant.name.lower() in latest_text or participant.role.lower() in latest_text:
            score += 80
        if "架构" in role_name and not (context.workspace_dir / "architecture.md").exists():
            score += 70
        if "架构" in role_name and any(keyword in latest_text for keyword in ["架构", "设计", "方案", "模块"]):
            score += 60
        if "产品" in role_name and any(keyword in latest_text for keyword in ["需求", "验收", "目标", "业务"]):
            score += 35
        if "开发" in role_name and any(keyword in latest_text for keyword in ["代码", "脚本", "实现", "修复"]):
            score += 45
        if ("驱动" in role_name or "bsp" in role_name) and any(keyword in latest_text for keyword in ["驱动", "bsp", "设备树", "gpio", "uart", "spi", "i2c", "内核"]):
            score += 50
        if ("构建" in role_name or "发布" in role_name) and any(keyword in latest_text for keyword in ["构建", "编译", "make", "运行", "发布", "binary"]):
            score += 55
        if "测试" in role_name and any(keyword in latest_text for keyword in ["测试", "验证", "运行", "结果"]):
            score += 55
        if "日志" in role_name and any(keyword in latest_text for keyword in ["日志", "串口", "报错", "异常", "dmesg", "输出"]):
            score += 45
        if "安全" in role_name and any(keyword in latest_text for keyword in ["安全", "风险", "漏洞"]):
            score += 35
        if "运维" in role_name and any(keyword in latest_text for keyword in ["部署", "环境", "上线", "主机"]):
            score += 35
        if "集成" in role_name and any(keyword in latest_text for keyword in ["集成", "联调", "接口"]):
            score += 35
        if "文档" in role_name and any(keyword in latest_text for keyword in ["文档", "说明", "readme", "交付"]):
            score += 35
        if "数据" in role_name and any(keyword in latest_text for keyword in ["数据", "指标", "分析"]):
            score += 35
        if "评审" in role_name and any(keyword in latest_text for keyword in ["评审", "通过", "结果"]):
            score += 25
        return score

    def _resolve_handoff_target(
        self,
        ai_participants: list[Participant],
        next_agent_hint: str | None,
        current_participant_id: str,
        visit_counts: dict[str, int],
    ) -> str | None:
        if not next_agent_hint:
            return None
        hint = next_agent_hint.strip().lower()
        for participant in ai_participants:
            if participant.participant_id == current_participant_id:
                continue
            if visit_counts.get(participant.participant_id, 0) >= 2:
                continue
            if hint in participant.participant_id.lower() or hint in participant.name.lower() or hint in participant.role.lower():
                return participant.participant_id
        return None

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

    def list_role_templates(self) -> list[dict[str, object]]:
        return [dict(item) for item in DEFAULT_ROLE_TEMPLATES]

    def build_participant_from_template(self, template_id: str) -> Participant:
        template = next((item for item in DEFAULT_ROLE_TEMPLATES if item["template_id"] == template_id), None)
        if template is None:
            raise ValueError(f"Unknown role template: {template_id}")
        return Participant(
            participant_id="new",
            name=str(template["name"]),
            role=str(template["role"]),
            participant_type=ParticipantType(str(template["participant_type"])),
            description=str(template.get("description", "")),
            enabled=bool(template.get("enabled", True)),
            llm_profile_id=str(template.get("llm_profile_id", "")),
            tools=list(template.get("tools", [])),
            system_prompt=str(template.get("system_prompt", "")),
        )

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

    def _open_tasks(self, room_id: str) -> list[TaskItem]:
        return [task for task in self.list_tasks(room_id) if task.status not in {TaskStatus.APPROVED, TaskStatus.DONE}]

    def _set_task_status_internal(self, room_id: str, task: TaskItem, status: TaskStatus, note: str | None = None) -> None:
        if task.status == status:
            return
        task.status = status
        task.updated_at = datetime.now()
        self.db.execute(
            "UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ? AND room_id = ?",
            (status.value, task.updated_at.isoformat(timespec="seconds"), task.task_id, room_id),
        )
        self._update_phase_for_tasks(room_id)
        if note:
            self.add_system_message(room_id, note)

    def _build_task_followup_message(self, room_id: str) -> str:
        open_tasks = self._open_tasks(room_id)
        if not open_tasks:
            return "当前任务已经全部闭环，请主持人决定是否结束。"
        task = open_tasks[0]
        if task.status == TaskStatus.REJECTED:
            return f"任务“{task.title}”仍未通过，请相关开发或构建角色继续修复，直到程序运行成功。"
        if task.status == TaskStatus.AWAITING_REVIEW:
            return f"任务“{task.title}”已经待评审，请评审 Agent 根据测试结果给出验收结论。"
        return f"请继续推进任务“{task.title}”，直到程序构建成功、运行成功并通过验收。"

    def _auto_progress_tasks(self, room_id: str, participant: Participant, turn: AgentTurn) -> None:
        open_tasks = self._open_tasks(room_id)
        if not open_tasks:
            return
        task = open_tasks[0]
        role_name = participant.role.lower()
        tool_outputs = turn.tool_outputs or []
        tool_map = {item.tool_id: item for item in tool_outputs}
        build_success = bool(tool_map.get("build_runner") and tool_map["build_runner"].details.get("success"))
        binary_success = bool(tool_map.get("binary_runner") and tool_map["binary_runner"].details.get("success"))
        test_success = bool(tool_map.get("test_runner") and tool_map["test_runner"].details.get("success"))
        acceptance_success = bool(tool_map.get("acceptance_check") and tool_map["acceptance_check"].details.get("accepted"))
        embedded_task = any(keyword in f"{task.title} {task.description} {task.acceptance_criteria}".lower() for keyword in ["嵌入式", "embedded", "gpio", "uart", "linux"]) or (self.role_store.workspace_dir(room_id) / "embedded_app.c").exists()
        has_code_artifact = any(
            str(item.details.get("path", "")).endswith(name)
            for item in tool_outputs
            for name in ["generated_script.py", "embedded_app.c", "Makefile"]
        )

        if task.status == TaskStatus.PENDING and ("产品" in role_name or "架构" in role_name or "开发" in role_name):
            self._set_task_status_internal(room_id, task, TaskStatus.IN_PROGRESS, f"任务状态自动推进：{task.title} -> in_progress")
            return
        if task.status in {TaskStatus.REJECTED, TaskStatus.PENDING} and ("开发" in role_name or "驱动" in role_name or "构建" in role_name) and has_code_artifact:
            self._set_task_status_internal(room_id, task, TaskStatus.IN_PROGRESS, f"任务状态自动推进：{task.title} -> in_progress")
            return
        if "测试" in role_name:
            if embedded_task and binary_success:
                self._set_task_status_internal(room_id, task, TaskStatus.AWAITING_REVIEW, f"任务状态自动推进：{task.title} -> awaiting_review")
                return
            if not embedded_task and (binary_success or test_success):
                self._set_task_status_internal(room_id, task, TaskStatus.AWAITING_REVIEW, f"任务状态自动推进：{task.title} -> awaiting_review")
                return
            if tool_map.get("binary_runner") or tool_map.get("test_runner"):
                self._set_task_status_internal(room_id, task, TaskStatus.REJECTED, f"任务状态自动推进：{task.title} -> rejected，等待继续修复")
                return
        if "评审" in role_name and (acceptance_success or turn.requires_moderator):
            self._set_task_status_internal(room_id, task, TaskStatus.APPROVED, f"任务状态自动推进：{task.title} -> approved")
            recent_decisions = self.list_decisions(room_id)
            if not recent_decisions or recent_decisions[0].reviewer_name != participant.name:
                self.record_review(room_id, True, participant.name, f"自动验收通过：{task.title}")

    def _set_phase(self, room_id: str, phase: MeetingPhase) -> None:
        self.db.execute("UPDATE rooms SET phase = ?, updated_at = ? WHERE room_id = ?", (phase.value, now_iso(), room_id))

    def _touch_room(self, room_id: str) -> None:
        self.db.execute("UPDATE rooms SET updated_at = ? WHERE room_id = ?", (now_iso(), room_id))

    def _next_participant_id(self, room_id: str) -> str:
        rows = self.list_participants(room_id)
        max_number = max((int(item.participant_id[1:]) for item in rows if item.participant_id.startswith("p")), default=0)
        return f"p{max_number + 1}"

    def _next_task_id(self, room_id: str) -> str:
        _ = room_id
        return f"t{uuid4().hex[:12]}"

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