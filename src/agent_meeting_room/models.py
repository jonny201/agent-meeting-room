from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ParticipantType(str, Enum):
    HUMAN = "human"
    AI = "ai"


class MessageKind(str, Enum):
    CHAT = "chat"
    SYSTEM = "system"
    REVIEW = "review"


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    DONE = "done"


class MeetingPhase(str, Enum):
    DISCOVERY = "discovery"
    PLANNING = "planning"
    EXECUTION = "execution"
    REVIEW = "review"
    COMPLETED = "completed"


class RoomStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    STOPPED = "stopped"


@dataclass(slots=True)
class Participant:
    participant_id: str
    name: str
    role: str
    participant_type: ParticipantType
    description: str = ""
    enabled: bool = True
    llm_profile_id: str = ""
    tools: list[str] = field(default_factory=list)
    system_prompt: str = ""


@dataclass(slots=True)
class Message:
    sender_id: str
    sender_name: str
    sender_role: str
    content: str
    kind: MessageKind
    created_at: datetime = field(default_factory=datetime.now)
    message_id: int | None = None


@dataclass(slots=True)
class TaskItem:
    task_id: str
    title: str
    description: str
    owner_id: str
    owner_name: str
    acceptance_criteria: str
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass(slots=True)
class ReviewDecision:
    approved: bool
    reviewer_name: str
    note: str
    created_at: datetime = field(default_factory=datetime.now)
    decision_id: int | None = None


@dataclass(slots=True)
class LLMProfile:
    profile_id: str
    name: str
    provider: str
    model: str
    base_url: str
    api_key: str
    temperature: float
    max_tokens: int
    enable_thinking: bool
    is_default: bool = False


@dataclass(slots=True)
class MemoryNote:
    memory_id: int | None = None
    title: str = ""
    content: str = ""
    tags: str = ""
    source: str = "manual"
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass(slots=True)
class RoomState:
    room_id: str
    room_name: str
    goal: str
    phase: MeetingPhase = MeetingPhase.DISCOVERY
    status: RoomStatus = RoomStatus.ACTIVE
    participants: list[Participant] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)
    tasks: list[TaskItem] = field(default_factory=list)
    decisions: list[ReviewDecision] = field(default_factory=list)


@dataclass(slots=True)
class RoomSummary:
    room_id: str
    room_name: str
    goal: str
    phase: MeetingPhase
    status: RoomStatus
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class ToolDefinition:
    tool_id: str
    name: str
    description: str
    category: str
