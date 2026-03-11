from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .llm_client import LLMClient
from .models import LLMProfile, MemoryNote, Message, Participant, RoomStatus, TaskItem, TaskStatus
from .tooling import ToolExecutionResult, execute_tools


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
    participants: list[Participant]
    workspace_dir: Path


@dataclass(slots=True)
class AgentTurn:
    reply_text: str
    next_agent_hint: str | None
    handoff_reason: str
    requires_moderator: bool = False
    tool_outputs: list[ToolExecutionResult] | None = None


class BaseAgent:
    def __init__(self, participant: Participant) -> None:
        self.participant = participant

    def should_reply(self, context: AgentContext) -> bool:
        raise NotImplementedError

    def plan_turn(self, context: AgentContext) -> AgentTurn:
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
        if self.participant.name.lower() in latest_text or self.participant.role.lower() in latest_text:
            return True

        if "主持人" in context.latest_message.sender_role and any(keyword in latest_text for keyword in ["停止讨论", "暂停讨论"]):
            return False
        if "主持人" in role_name:
            return False
        if "架构" in role_name:
            return any(keyword in latest_text for keyword in ["架构", "设计", "框架", "模块", "方案", "程序"]) or not active_tasks
        if "开发" in role_name:
            return any(keyword in latest_text for keyword in ["代码", "脚本", "实现", "开发", "修复", "接口"])
        if "驱动" in role_name or "bsp" in role_name:
            return any(keyword in latest_text for keyword in ["驱动", "bsp", "设备树", "gpio", "uart", "spi", "i2c", "内核"])
        if "构建" in role_name or "发布" in role_name:
            return any(keyword in latest_text for keyword in ["构建", "编译", "make", "binary", "发布", "运行"])
        if "测试" in role_name:
            return any(keyword in latest_text for keyword in ["测试", "验证", "运行", "结果", "完成"])
        if "日志" in role_name:
            return any(keyword in latest_text for keyword in ["日志", "串口", "报错", "异常", "输出", "dmesg"])
        if "评审" in role_name:
            return any(keyword in latest_text for keyword in ["评审", "结果", "通过", "风险"])
        if "产品" in role_name:
            return any(keyword in latest_text for keyword in ["需求", "验收", "用户", "目标", "流程"])
        return any(keyword in latest_text for keyword in ["问题", "建议", "风险", "下一步"])

    def plan_turn(self, context: AgentContext) -> AgentTurn:
        role_name = self.participant.role.lower()
        latest_text = context.latest_message.content if context.latest_message else ""
        active_tasks = [task for task in context.tasks if task.status not in {TaskStatus.DONE, TaskStatus.APPROVED}]
        tool_outputs = execute_tools(self.participant.tools, self.participant.name, latest_text, context.room_goal, context.workspace_dir)
        tool_summary = " ".join(result.summary for result in tool_outputs)

        if "架构" in role_name or "architect" in role_name:
            reply_text = self._architect_reply(context.room_goal, latest_text, active_tasks, tool_summary)
        elif "测试" in role_name or "tester" in role_name:
            reply_text = self._tester_reply(latest_text, active_tasks, tool_summary)
        elif "开发" in role_name or "engineer" in role_name or "programmer" in role_name:
            reply_text = self._developer_reply(latest_text, active_tasks, tool_summary)
        elif "评审" in role_name or "review" in role_name:
            reply_text = self._reviewer_reply(active_tasks, tool_summary)
        else:
            reply_text = self._expert_reply(context.room_goal, latest_text, active_tasks, tool_summary)

        next_hint, handoff_reason, requires_moderator = self._choose_next_agent(context, tool_outputs)
        handoff_target = "主持人" if requires_moderator else (next_hint or "主持人")
        reply_text = f"{reply_text}\n\n建议下一位：{handoff_target}。原因：{handoff_reason}"
        return AgentTurn(
            reply_text=reply_text,
            next_agent_hint=next_hint,
            handoff_reason=handoff_reason,
            requires_moderator=requires_moderator,
            tool_outputs=tool_outputs,
        )

    def _choose_next_agent(
        self,
        context: AgentContext,
        tool_outputs: list[ToolExecutionResult],
    ) -> tuple[str | None, str, bool]:
        role_name = self.participant.role.lower()
        latest_text = context.latest_message.content.lower() if context.latest_message else ""
        available_roles = [participant.role.lower() for participant in context.participants if participant.enabled]
        test_result = next((item for item in tool_outputs if item.tool_id == "test_runner"), None)
        acceptance_result = next((item for item in tool_outputs if item.tool_id == "acceptance_check"), None)
        risk_result = next((item for item in tool_outputs if item.tool_id == "risk_matrix"), None)
        has_script = any(str(item.details.get("path", "")).endswith("generated_script.py") for item in tool_outputs)
        has_embedded_c = any(str(item.details.get("path", "")).endswith("embedded_app.c") for item in tool_outputs)
        build_result = next((item for item in tool_outputs if item.tool_id == "build_runner"), None)
        binary_result = next((item for item in tool_outputs if item.tool_id == "binary_runner"), None)
        embedded_flow = has_embedded_c or any(keyword in f"{context.room_goal} {latest_text}" for keyword in ["嵌入式", "embedded", "gpio", "uart", "linux"])

        def has_role(keyword: str) -> bool:
            return any(keyword in role for role in available_roles)

        if "产品" in role_name:
            return ("架构师Agent", "需求边界已经补齐，应该让架构师先收敛方案。", False)
        if "架构" in role_name and has_role("驱动") and any(keyword in latest_text for keyword in ["驱动", "bsp", "设备树", "gpio", "uart", "spi", "i2c"]):
            return ("BSP与驱动Agent", "当前任务涉及板级与驱动约束，应该先让 BSP 与驱动角色确认边界。", False)
        if "架构" in role_name and has_role("开发"):
            return ("开发Agent", "方案已经清晰，下一步应由开发落地实现。", False)
        if "驱动" in role_name and has_role("开发"):
            return ("开发Agent", "板级约束已经明确，应该交给应用开发落实代码。", False)
        if "开发" in role_name:
            if (has_embedded_c or has_script) and has_role("构建"):
                return ("构建发布Agent", "已经形成源码和构建文件，应该先完成构建。", False)
            if has_script and has_role("测试"):
                return ("测试Agent", "已经形成可执行脚本，应该立即进入验证。", False)
            if has_role("文档"):
                return ("文档Agent", "实现信息已经更新，可以同步补文档。", False)
        if "构建" in role_name:
            if build_result and bool(build_result.details.get("success")) and has_role("测试"):
                return ("测试Agent", "构建成功，应该把二进制交给测试执行。", False)
            if build_result and not bool(build_result.details.get("success", True)) and has_role("开发"):
                return ("开发Agent", "构建失败，需要开发修复源码或构建脚本。", False)
        if "测试" in role_name:
            if has_role("日志") and any(keyword in latest_text for keyword in ["失败", "异常", "日志", "报错"]):
                return ("日志分析Agent", "测试已经发现异常，应由日志分析角色先定位根因。", False)
            if embedded_flow:
                if binary_result and bool(binary_result.details.get("success")) and has_role("评审"):
                    return ("评审Agent", "嵌入式程序已经真实运行成功，可以进入评审验收。", False)
                if binary_result and not bool(binary_result.details.get("success", True)) and has_role("开发"):
                    return ("开发Agent", "嵌入式程序尚未运行成功，需要继续修复。", False)
                if build_result and not bool(build_result.details.get("success", True)) and has_role("开发"):
                    return ("开发Agent", "构建仍未通过，需要开发继续修复。", False)
            if test_result and bool(test_result.details.get("success")):
                if has_role("安全") and any(keyword in latest_text for keyword in ["安全", "漏洞"]):
                    return ("安全审计Agent", "功能测试通过后，应继续做安全检查。", False)
                if has_role("评审"):
                    return ("评审Agent", "测试通过后可以进入评审收口。", False)
            if binary_result and bool(binary_result.details.get("success")) and has_role("评审"):
                return ("评审Agent", "程序已经构建并运行成功，可以进入评审验收。", False)
            if test_result and not bool(test_result.details.get("success", True)) and has_role("开发"):
                return ("开发Agent", "测试失败，需要先回到开发修复。", False)
            if binary_result and not bool(binary_result.details.get("success", True)) and has_role("开发"):
                return ("开发Agent", "程序运行失败，需要继续修复。", False)
        if "日志" in role_name:
            if has_role("开发"):
                return ("开发Agent", "日志已经指向根因，应该回到开发修复。", False)
        if "安全" in role_name:
            if risk_result and str(risk_result.details.get("level", "")).lower() in {"high", "critical"} and has_role("开发"):
                return ("开发Agent", "安全检查发现高风险，需要开发优先修复。", False)
            if has_role("运维"):
                return ("运维Agent", "安全检查完成，应确认环境与交付条件。", False)
        if "运维" in role_name:
            if has_role("集成"):
                return ("集成Agent", "环境确认后应继续检查集成链路。", False)
            if has_role("评审"):
                return ("评审Agent", "部署条件已具备，可以进入评审。", False)
        if "集成" in role_name:
            if has_role("文档"):
                return ("文档Agent", "集成路径明确后应补充交付文档。", False)
            if has_role("评审"):
                return ("评审Agent", "集成检查完成，应进入评审。", False)
        if "文档" in role_name and has_role("评审"):
            return ("评审Agent", "文档已补齐，应由评审统一判断是否收口。", False)
        if "数据" in role_name and has_role("产品"):
            return ("产品专家Agent", "结果分析已完成，应回到产品确认验收口径。", False)
        if "评审" in role_name:
            all_closed = bool(context.tasks) and all(task.status in {TaskStatus.APPROVED, TaskStatus.DONE} for task in context.tasks)
            looks_good = any(keyword in latest_text for keyword in ["完成", "通过", "没问题", "收口"]) or bool(acceptance_result and acceptance_result.details.get("accepted"))
            if all_closed or looks_good:
                return (None, "所有 agent 当前都认为问题已收敛，应该交由主持人决定继续还是结束。", True)
            if has_role("开发"):
                return ("开发Agent", "评审发现仍有未闭环事项，需要继续回到开发处理。", False)
        return (None, "当前没有更合适的自动接力对象，建议主持人判断下一步。", True)

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

    def plan_turn(self, context: AgentContext) -> AgentTurn:
        tool_outputs = execute_tools(self.participant.tools, self.participant.name, context.latest_message.content if context.latest_message else "", context.room_goal, context.workspace_dir)
        messages = self._build_messages(context)
        result = self.client.call(messages)
        if result.get("success") and result.get("content"):
            merged = str(result["content"]).strip()
            if tool_outputs:
                merged = f"{merged}\n\n工具执行：" + "；".join(item.summary for item in tool_outputs)
            next_hint, handoff_reason, requires_moderator = RuleBasedAgent(self.participant)._choose_next_agent(context, tool_outputs)
            merged = f"{merged}\n\n建议下一位：{'主持人' if requires_moderator else (next_hint or '主持人')}。原因：{handoff_reason}"
            return AgentTurn(
                reply_text=merged,
                next_agent_hint=next_hint,
                handoff_reason=handoff_reason,
                requires_moderator=requires_moderator,
                tool_outputs=tool_outputs,
            )

        fallback = RuleBasedAgent(self.participant).plan_turn(context)
        error_text = result.get("error", "unknown error")
        fallback.reply_text = f"LLM 调用失败，已切换到本地策略。原因：{error_text}。{fallback.reply_text}"
        return fallback

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
            "每次输出都必须判断下一位最适合接力的角色，或者明确交还主持人。"
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
            "请用你的角色身份给出下一条发言，并显式说明建议下一位由谁接力。"
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