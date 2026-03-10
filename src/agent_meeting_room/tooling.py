from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .models import ToolDefinition


@dataclass(slots=True)
class ToolExecutionResult:
    tool_id: str
    summary: str


def execute_tools(tool_ids: list[str], participant_name: str, latest_text: str, goal: str, workspace_dir: Path) -> list[ToolExecutionResult]:
    """根据角色持有的工具，在会议室工作目录中执行轻量操作。"""

    results: list[ToolExecutionResult] = []
    workspace_dir.mkdir(parents=True, exist_ok=True)
    lowered = latest_text.lower()

    if "task_breakdown" in tool_ids and any(keyword in latest_text for keyword in ["任务", "拆解", "计划", "步骤", "需求"]):
        results.append(
            ToolExecutionResult(
                tool_id="task_breakdown",
                summary=(
                    f"{participant_name} 给出任务拆解建议：1）先确认目标；2）再形成产物；3）最后执行测试与评审。"
                ),
            )
        )

    if "architecture_design" in tool_ids and any(keyword in latest_text for keyword in ["架构", "框架", "模块", "设计", "程序"]):
        architecture_path = workspace_dir / "architecture.md"
        architecture_path.write_text(
            "# 软件框架草案\n\n"
            f"- 目标：{goal}\n"
            "- 分层：界面层 / 服务层 / 工具层 / 持久化层\n"
            "- 关键模块：会议室管理、角色编排、工具执行、记忆沉淀\n",
            encoding="utf-8",
        )
        results.append(
            ToolExecutionResult(
                tool_id="architecture_design",
                summary=f"已在工作目录生成架构草案文件：{architecture_path.name}。",
            )
        )

    if "code_writer" in tool_ids and any(keyword in latest_text for keyword in ["代码", "脚本", "python", "程序", "实现"]):
        script_path = workspace_dir / "generated_script.py"
        script_path.write_text(
            "# 这是会议室自动生成的脚本草案\n"
            "from __future__ import annotations\n\n"
            "def main() -> None:\n"
            f"    print('当前目标: {goal}')\n"
            f"    print('最近指令: {latest_text}')\n\n"
            "if __name__ == '__main__':\n"
            "    main()\n",
            encoding="utf-8",
        )
        results.append(
            ToolExecutionResult(
                tool_id="code_writer",
                summary=f"已在工作目录生成脚本文件：{script_path.name}。",
            )
        )

    if "artifact_reader" in tool_ids:
        artifacts = sorted(path.name for path in workspace_dir.iterdir() if path.is_file())
        if artifacts:
            results.append(
                ToolExecutionResult(
                    tool_id="artifact_reader",
                    summary=f"当前工作目录已有产物：{', '.join(artifacts)}。",
                )
            )

    if "test_runner" in tool_ids and any(keyword in latest_text for keyword in ["测试", "验证", "运行", "结果"]):
        script_path = workspace_dir / "generated_script.py"
        if script_path.exists():
            completed = subprocess.run(
                [sys.executable, str(script_path)],
                cwd=str(workspace_dir),
                capture_output=True,
                text=True,
                timeout=12,
                check=False,
            )
            output = (completed.stdout or completed.stderr or "没有输出").strip()
            results.append(
                ToolExecutionResult(
                    tool_id="test_runner",
                    summary=f"测试执行完成，退出码 {completed.returncode}，输出：{output}",
                )
            )
        else:
            results.append(
                ToolExecutionResult(
                    tool_id="test_runner",
                    summary="测试未执行，因为当前工作目录中还没有 generated_script.py。",
                )
            )

    if "review_summary" in tool_ids and any(keyword in lowered for keyword in ["结果", "完成", "通过", "测试", "评审"]):
        results.append(
            ToolExecutionResult(
                tool_id="review_summary",
                summary="评审建议：确认目标是否满足、产物是否存在、测试是否通过，再决定继续还是停止讨论。",
            )
        )

    return results


def build_tool_definitions(tool_payloads: list[dict[str, str]]) -> list[ToolDefinition]:
    return [ToolDefinition(**payload) for payload in tool_payloads]