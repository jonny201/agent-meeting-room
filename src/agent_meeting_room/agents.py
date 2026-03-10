from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .llm_client import LLMClient
from .models import LLMProfile, MemoryNote, Message, Participant, RoomStatus, TaskItem, TaskStatus
from .tooling import execute_tools


@dataclass(slots=True)
class AgentContext:
    room_id: str
    room_name: str
    room_goal: str
    room_status: RoomStatus
    latest_message: Message | None
    tasks: list[TaskItem]
    recent_messages: list[Message]
    memories: list[MemoryNote]
    workspace_dir: Path


class BaseAgent:
    def __init__(self, participant: Participant) -> None:
        self.participant = participant

    def should_reply(self, context: AgentContext) -> bool:
        raise NotImplementedError

    def generate_reply(self, context: AgentContext) -> str:
        raise NotImplementedError


class RuleBasedAgent(BaseAgent):
    """Generate simple role-driven replies for offline prototype use."""

    def should_reply(self, context: AgentContext) -> bool:
        if context.room_status is not RoomStatus.ACTIVE or context.latest_message is None:
            return False
        if context.latest_message.sender_id == self.participant.participant_id:
            return False

        latest_text = context.latest_message.content.lower()
        role_name = self.participant.role.lower()
        active_tasks = [task for task in context.tasks if task.status not in {TaskStatus.DONE, TaskStatus.APPROVED}]

        if any(keyword in latest_text for keyword in ["停止讨论", "暂停讨论"]):
            return False
        if "主持人" in role_name:
            return False
        if "架构" in role_name:
            return any(keyword in latest_text for keyword in ["架构", "设计", "框架", "模块", "方案", "程序"]) or not active_tasks
        if "开发" in role_name:
            return any(keyword in latest_text for keyword in ["代码", "脚本", "实现", "开发", "修复", "接口"])
        if "测试" in role_name:
            return any(keyword in latest_text for keyword in ["测试", "验证", "运行", "结果", "完成"])
        if "评审" in role_name:
            return any(keyword in latest_text for keyword in ["评审", "结果", "完成", "通过", "风险"])
        if "产品" in role_name:
            return any(keyword in latest_text for keyword in ["需求", "验收", "用户", "目标", "流程"])
        return any(keyword in latest_text for keyword in ["问题", "建议", "风险", "下一步"])

    def generate_reply(self, context: AgentContext) -> str:
        role_name = self.participant.role.lower()
        latest_text = context.latest_message.content if context.latest_message else ""
        active_tasks = [task for task in context.tasks if task.status not in {TaskStatus.DONE, TaskStatus.APPROVED}]
        tool_outputs = execute_tools(self.participant.tools, self.participant.name, latest_text, context.room_goal, context.workspace_dir)
        tool_summary = " ".join(result.summary for result in tool_outputs)

        if "架构" in role_name or "architect" in role_name:
            return self._architect_reply(context.room_goal, latest_text, active_tasks, tool_summary)
        if "测试" in role_name or "tester" in role_name:
            return self._tester_reply(latest_text, active_tasks, tool_summary)
        if "开发" in role_name or "engineer" in role_name or "programmer" in role_name:
            return self._developer_reply(latest_text, active_tasks, tool_summary)
        if "评审" in role_name or "review" in role_name:
            return self._reviewer_reply(active_tasks, tool_summary)
        return self._expert_reply(context.room_goal, latest_text, active_tasks, tool_summary)

    def _architect_reply(self, goal: str, latest_text: str, active_tasks: list[TaskItem], tool_summary: str) -> str:
        task_hint = active_tasks[0].title if active_tasks else "先明确模块边界"
        return (
            f"从架构视角看，当前目标是：{goal}。"
            f"我建议先拆分关键模块，再推进任务“{task_hint}”。"
            f"当前讨论重点可以放在职责边界、数据流和风险控制上。"
            f" 如果刚才的内容是“{latest_text}”，那么下一步应确认接口与验收标准。"
            f" {tool_summary}".strip()
        )

    def _tester_reply(self, latest_text: str, active_tasks: list[TaskItem], tool_summary: str) -> str:
        task_hint = active_tasks[0].title if active_tasks else "当前还没有测试任务"
        return (
            f"测试视角建议补充可验证条件。当前优先关注：{task_hint}。"
            f"对于“{latest_text}”，我会补充边界条件、异常流程和回归检查点。"
            f" {tool_summary}".strip()
        )

    def _developer_reply(self, latest_text: str, active_tasks: list[TaskItem], tool_summary: str) -> str:
        task_hint = active_tasks[0].title if active_tasks else "先建立最小可运行版本"
        return (
            f"开发视角建议先做可运行骨架。当前可以落地的任务是：{task_hint}。"
            f"如果围绕“{latest_text}”继续推进，我建议先实现主流程，再补充细节。"
            f" {tool_summary}".strip()
        )

    def _reviewer_reply(self, active_tasks: list[TaskItem], tool_summary: str) -> str:
        if not active_tasks:
            return f"评审视角看，当前没有阻塞任务，可以检查是否满足目标并决定是否进入下一阶段。 {tool_summary}".strip()
        task_hint = ", ".join(task.title for task in active_tasks[:2])
        return f"评审视角建议先核对这些任务的产出是否满足验收标准：{task_hint}。 {tool_summary}".strip()

    def _expert_reply(self, goal: str, latest_text: str, active_tasks: list[TaskItem], tool_summary: str) -> str:
        task_hint = active_tasks[0].title if active_tasks else "建议先形成任务拆解"
        return (
            f"结合目标“{goal}”，我建议围绕“{latest_text}”继续细化。"
            f" 目前最值得推进的是：{task_hint}。"
            f" {tool_summary}".strip()
        )


class LLMDrivenAgent(BaseAgent):
    def __init__(self, participant: Participant, profile: LLMProfile) -> None:
        super().__init__(participant)
        self.profile = profile
        self.client = LLMClient(profile)

    def should_reply(self, context: AgentContext) -> bool:
        return RuleBasedAgent(self.participant).should_reply(context)

    def generate_reply(self, context: AgentContext) -> str:
        tool_outputs = execute_tools(self.participant.tools, self.participant.name, context.latest_message.content if context.latest_message else "", context.room_goal, context.workspace_dir)
        messages = self._build_messages(context)
        result = self.client.call(messages)
        if result.get("success") and result.get("content"):
            merged = str(result["content"]).strip()
            if tool_outputs:
                merged = f"{merged}\n\n工具执行：" + "；".join(item.summary for item in tool_outputs)
            return merged

        fallback = RuleBasedAgent(self.participant).generate_reply(context)
        error_text = result.get("error", "unknown error")
        return f"LLM 调用失败，已切换到本地策略。原因：{error_text}。{fallback}"

    def _build_messages(self, context: AgentContext) -> list[dict[str, str]]:
        latest_text = context.latest_message.content if context.latest_message else ""
        tasks_text = "\n".join(
            f"- {task.title} | owner={task.owner_name} | status={task.status.value} | acceptance={task.acceptance_criteria}"
            for task in context.tasks[-8:]
        ) or "- 当前没有任务"
        history_text = "\n".join(
            f"[{message.sender_role}] {message.sender_name}: {message.content}"
            for message in context.recent_messages[-12:]
        ) or "- 当前没有历史消息"
        memory_text = "\n".join(
            f"- {memory.title}: {memory.content}"
            for memory in context.memories[:6]
        ) or "- 当前没有相关长期记忆"
        tool_text = "\n".join(f"- {tool_id}" for tool_id in self.participant.tools) or "- 当前没有配置工具"

        system_prompt = (
            f"你现在位于会议室 {context.room_name}，角色是 {self.participant.role}，名称是 {self.participant.name}。"
            "你的任务是围绕目标推进问题讨论、任务拆分、风险识别和下一步建议。"
            "只在当前消息和你的职责相关时才回复。"
            "输出必须具体、可执行、简洁，不要写空话。"
            "如果需要推进，请给出明确的行动建议、责任人建议或验收点。"
            f" {self.participant.system_prompt}".strip()
        )
        user_prompt = (
            f"会议目标：{context.room_goal}\n"
            f"你的角色描述：{self.participant.description or self.participant.role}\n"
            f"你持有的工具：\n{tool_text}\n\n"
            f"最近一条消息：{latest_text}\n\n"
            f"当前任务：\n{tasks_text}\n\n"
            f"相关长期记忆：\n{memory_text}\n\n"
            f"近期对话：\n{history_text}\n\n"
            "请用你的角色身份给出下一条发言。"
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]


def build_agent(participant: Participant, profile: LLMProfile | None = None) -> BaseAgent:
    # 测试或离线环境下可以显式关闭远程大模型调用。
    if profile is not None and os.getenv("AMR_DISABLE_LLM", "0") != "1":
        return LLMDrivenAgent(participant, profile)
    return RuleBasedAgent(participant)