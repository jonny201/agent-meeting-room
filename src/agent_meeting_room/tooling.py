from __future__ import annotations

import json
import os
import platform
import re
import shlex
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .models import ToolDefinition


@dataclass(slots=True)
class ToolExecutionResult:
    tool_id: str
    summary: str
    details: dict[str, object] = field(default_factory=dict)


COMMAND_BLACKLIST = ["rm -rf", "shutdown", "reboot", "mkfs", "dd if=", "format "]


def _state_file(workspace_dir: Path) -> Path:
    return workspace_dir / ".amr_shell_state.json"


def _load_shell_state(workspace_dir: Path) -> dict[str, object]:
    state_path = _state_file(workspace_dir)
    if not state_path.exists():
        return {"cwd": str(workspace_dir)}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"cwd": str(workspace_dir)}


def _save_shell_state(workspace_dir: Path, state: dict[str, object]) -> None:
    _state_file(workspace_dir).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _truncate(text: str, limit: int = 500) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "...<truncated>"


def _is_command_allowed(command: str) -> tuple[bool, str]:
    lowered = command.lower().strip()
    if not lowered:
        return False, "空命令不执行。"
    for blocked in COMMAND_BLACKLIST:
        if blocked in lowered:
            return False, f"命令命中黑名单，已阻止：{blocked}"
    return True, "allowed"


def _extract_file_hint(text: str) -> str | None:
    match = re.search(r"([\w\-.]+\.(?:py|md|txt|json|log|yaml|yml))", text, re.IGNORECASE)
    return match.group(1) if match else None


def _ensure_knowledge_base(workspace_dir: Path, goal: str) -> Path:
    knowledge_dir = workspace_dir / "knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    seed_path = knowledge_dir / "room_goal.md"
    if not seed_path.exists():
        seed_path.write_text(f"# 会议室目标\n\n{goal}\n", encoding="utf-8")
    return knowledge_dir


def _looks_like_embedded_request(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in ["嵌入式", "embedded", "linux", "gpio", "uart", "spi", "i2c", "设备树", "驱动", "板卡", "c程序", "交叉编译"])


def _find_compiler() -> str | None:
    for candidate in ["gcc", "cc", "clang", "aarch64-openeuler-linux-gcc"]:
        completed = subprocess.run(f"command -v {candidate}", shell=True, capture_output=True, text=True, timeout=3, check=False)
        if completed.returncode == 0 and completed.stdout.strip():
            return candidate
    return None


def execute_tools(tool_ids: list[str], participant_name: str, latest_text: str, goal: str, workspace_dir: Path) -> list[ToolExecutionResult]:
    """根据角色持有的工具，在会议室工作目录中执行轻量操作。"""

    results: list[ToolExecutionResult] = []
    workspace_dir.mkdir(parents=True, exist_ok=True)
    lowered = latest_text.lower()
    shell_state = _load_shell_state(workspace_dir)
    knowledge_dir = _ensure_knowledge_base(workspace_dir, goal)

    if "get_environment" in tool_ids:
        env_payload = {
            "cwd": str(shell_state.get("cwd", workspace_dir)),
            "os": platform.system(),
            "release": platform.release(),
            "python": sys.version.split()[0],
            "host": socket.gethostname(),
            "user": os.getenv("USERNAME") or os.getenv("USER") or "unknown",
        }
        results.append(
            ToolExecutionResult(
                tool_id="get_environment",
                summary=f"运行环境：{env_payload['os']} {env_payload['release']}，Python {env_payload['python']}，cwd={env_payload['cwd']}。",
                details=env_payload,
            )
        )

    if "change_directory" in tool_ids and any(keyword in lowered for keyword in ["切换目录", "进入目录", "workspace", "工作目录"]):
        shell_state["cwd"] = str(workspace_dir)
        _save_shell_state(workspace_dir, shell_state)
        results.append(
            ToolExecutionResult(
                tool_id="change_directory",
                summary=f"当前工具目录已切换到 {workspace_dir.name} 工作目录。",
                details={"cwd": str(workspace_dir)},
            )
        )

    if "list_directory" in tool_ids:
        entries = sorted(path.name for path in workspace_dir.iterdir())[:30]
        results.append(
            ToolExecutionResult(
                tool_id="list_directory",
                summary=f"工作目录内容：{', '.join(entries) if entries else '当前为空'}。",
                details={"entries": entries},
            )
        )

    if "task_breakdown" in tool_ids and any(keyword in latest_text for keyword in ["任务", "拆解", "计划", "步骤", "需求"]):
        results.append(
            ToolExecutionResult(
                tool_id="task_breakdown",
                summary=f"{participant_name} 给出任务拆解建议：1）先确认目标；2）再形成产物；3）最后执行测试与评审。",
                details={"steps": ["确认目标", "形成产物", "执行测试与评审"]},
            )
        )

    if "test_plan" in tool_ids and any(keyword in lowered for keyword in ["测试", "验证", "回归", "检查"]):
        results.append(
            ToolExecutionResult(
                tool_id="test_plan",
                summary="已生成测试思路：主流程、异常流程、边界输入、回归验证。",
                details={"cases": ["主流程", "异常流程", "边界输入", "回归验证"]},
            )
        )

    if "architecture_design" in tool_ids and (
        any(keyword in latest_text for keyword in ["架构", "框架", "模块", "设计", "程序"])
        or _looks_like_embedded_request(latest_text + " " + goal)
        or not (workspace_dir / "architecture.md").exists()
    ):
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
                details={"path": str(architecture_path)},
            )
        )

    if "embedded_c_writer" in tool_ids and (_looks_like_embedded_request(latest_text + " " + goal) or (workspace_dir / "architecture.md").exists()):
        c_path = workspace_dir / "embedded_app.c"
        c_path.write_text(
            "#include <stdio.h>\n"
            "#include <string.h>\n\n"
            "int main(int argc, char *argv[]) {\n"
            "    const char *board = \"demo-board\";\n"
            "    const char *mode = \"normal\";\n"
            "    if (argc > 1) {\n"
            "        board = argv[1];\n"
            "    }\n"
            "    if (argc > 2) {\n"
            "        mode = argv[2];\n"
            "    }\n"
            "    printf(\"board=%s\\n\", board);\n"
            "    printf(\"mode=%s\\n\", mode);\n"
            "    printf(\"status=embedded-linux-demo-ok\\n\");\n"
            "    return strcmp(mode, \"fail\") == 0 ? 1 : 0;\n"
            "}\n",
            encoding="utf-8",
        )
        results.append(
            ToolExecutionResult(
                tool_id="embedded_c_writer",
                summary=f"已生成嵌入式 Linux C 程序骨架：{c_path.name}。",
                details={"path": str(c_path)},
            )
        )

    if "makefile_writer" in tool_ids and ((workspace_dir / "embedded_app.c").exists() or _looks_like_embedded_request(latest_text + " " + goal)):
        makefile_path = workspace_dir / "Makefile"
        makefile_path.write_text(
            "CC ?= gcc\n"
            "CFLAGS ?= -O2 -Wall -Wextra\n"
            "TARGET := embedded_app\n"
            "SRC := embedded_app.c\n\n"
            "all: $(TARGET)\n\n"
            "$(TARGET): $(SRC)\n"
            "\t$(CC) $(CFLAGS) -o $@ $<\n\n"
            "clean:\n"
            "\trm -f $(TARGET)\n",
            encoding="utf-8",
        )
        results.append(
            ToolExecutionResult(
                tool_id="makefile_writer",
                summary=f"已生成构建文件：{makefile_path.name}。",
                details={"path": str(makefile_path)},
            )
        )
    if "document_writer" in tool_ids and any(keyword in lowered for keyword in ["文档", "说明", "readme", "交付"]):
        document_path = workspace_dir / "delivery_note.md"
        document_path.write_text(
            "# 交付说明\n\n"
            f"- 目标：{goal}\n"
            f"- 最新上下文：{latest_text}\n"
            "- 建议阅读：architecture.md、generated_script.py、test_report.txt\n",
            encoding="utf-8",
        )
        results.append(
            ToolExecutionResult(
                tool_id="document_writer",
                summary=f"已生成交付说明文件：{document_path.name}。",
                details={"path": str(document_path)},
            )
        )

    if "code_writer" in tool_ids and not _looks_like_embedded_request(latest_text + " " + goal) and any(keyword in latest_text for keyword in ["代码", "脚本", "python", "程序", "实现"]):
        script_path = workspace_dir / "generated_script.py"
        script_path.write_text(
            "# 这是会议室自动生成的脚本草案\n"
            "from __future__ import annotations\n\n"
            "def main() -> None:\n"
            f"    goal = {goal!r}\n"
            f"    latest = {latest_text!r}\n"
            "    print('当前目标:', goal)\n"
            "    print('最近指令:', latest)\n\n"
            "if __name__ == '__main__':\n"
            "    main()\n",
            encoding="utf-8",
        )
        results.append(
            ToolExecutionResult(
                tool_id="code_writer",
                summary=f"已在工作目录生成脚本文件：{script_path.name}。",
                details={"path": str(script_path)},
            )
        )

    if "write_file" in tool_ids and any(keyword in lowered for keyword in ["写入", "保存", "记录"]):
        note_path = workspace_dir / "agent_notes.txt"
        with note_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{participant_name}] {latest_text}\n")
        results.append(
            ToolExecutionResult(
                tool_id="write_file",
                summary=f"已把当前上下文写入 {note_path.name}。",
                details={"path": str(note_path)},
            )
        )

    if "artifact_reader" in tool_ids:
        artifacts = sorted(path.name for path in workspace_dir.iterdir() if path.is_file())
        if artifacts:
            results.append(
                ToolExecutionResult(
                    tool_id="artifact_reader",
                    summary=f"当前工作目录已有产物：{', '.join(artifacts)}。",
                    details={"entries": artifacts},
                )
            )

    if "workspace_snapshot" in tool_ids:
        snapshot = [str(path.relative_to(workspace_dir)) for path in sorted(workspace_dir.rglob("*")) if path.is_file()][:50]
        results.append(
            ToolExecutionResult(
                tool_id="workspace_snapshot",
                summary=f"工作区快照：{', '.join(snapshot[:12]) if snapshot else '没有文件'}。",
                details={"entries": snapshot},
            )
        )

    if "search_text" in tool_ids and any(keyword in lowered for keyword in ["查找", "搜索", "grep", "关键字"]):
        query_terms = [term for term in re.split(r"\s+", latest_text) if len(term) >= 2][:5]
        matches: list[str] = []
        for file_path in workspace_dir.rglob("*"):
            if not file_path.is_file() or file_path.stat().st_size > 512 * 1024:
                continue
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            lowered_content = content.lower()
            if any(term.lower() in lowered_content for term in query_terms):
                matches.append(file_path.name)
        if matches:
            results.append(
                ToolExecutionResult(
                    tool_id="search_text",
                    summary=f"文本搜索命中：{', '.join(matches[:10])}。",
                    details={"matches": matches[:20]},
                )
            )

    if "read_file" in tool_ids:
        hinted_name = _extract_file_hint(latest_text)
        target_path = workspace_dir / hinted_name if hinted_name else None
        if target_path and target_path.exists():
            content = target_path.read_text(encoding="utf-8", errors="replace").splitlines()[:20]
            results.append(
                ToolExecutionResult(
                    tool_id="read_file",
                    summary=f"已读取文件 {target_path.name} 的前 {len(content)} 行。",
                    details={"path": str(target_path), "preview": content},
                )
            )

    if "dependency_scan" in tool_ids:
        dependencies: list[str] = []
        for candidate in [workspace_dir / "generated_script.py", workspace_dir / "architecture.md"]:
            if candidate.exists():
                text = candidate.read_text(encoding="utf-8", errors="replace")
                dependencies.extend(sorted({match.group(1) for match in re.finditer(r"^(?:from|import)\s+([\w\.]+)", text, re.MULTILINE)}))
        results.append(
            ToolExecutionResult(
                tool_id="dependency_scan",
                summary=f"依赖扫描结果：{', '.join(dependencies) if dependencies else '未发现额外依赖'}。",
                details={"dependencies": dependencies},
            )
        )

    if "cross_compile_probe" in tool_ids:
        compiler = _find_compiler()
        make_exists = subprocess.run("make --version", shell=True, capture_output=True, text=True, timeout=5, check=False)
        details = {
            "compiler": compiler or "not-found",
            "make": make_exists.returncode == 0,
        }
        results.append(
            ToolExecutionResult(
                tool_id="cross_compile_probe",
                summary=(
                    f"编译环境探测：compiler={details['compiler']}，make={'ok' if details['make'] else 'missing'}。"
                ),
                details=details,
            )
        )

    if "build_runner" in tool_ids and ((workspace_dir / "embedded_app.c").exists() or any(keyword in lowered for keyword in ["构建", "编译", "make", "build"])):
        compiler = _find_compiler()
        makefile_path = workspace_dir / "Makefile"
        make_available = subprocess.run("command -v make", shell=True, capture_output=True, text=True, timeout=3, check=False).returncode == 0
        if makefile_path.exists() and make_available:
            command = "make"
        elif compiler and (workspace_dir / "embedded_app.c").exists():
            command = f"{compiler} -O2 -Wall -Wextra -o embedded_app embedded_app.c"
        else:
            command = ""
        if command:
            completed = subprocess.run(command, cwd=str(workspace_dir), shell=True, capture_output=True, text=True, timeout=30, check=False)
            output = (completed.stdout or completed.stderr or "没有输出").strip()
            results.append(
                ToolExecutionResult(
                    tool_id="build_runner",
                    summary=f"构建执行完成，退出码 {completed.returncode}，输出：{_truncate(output)}",
                    details={"success": completed.returncode == 0, "exit_code": completed.returncode, "stdout": output, "command": command},
                )
            )
        else:
            results.append(
                ToolExecutionResult(
                    tool_id="build_runner",
                    summary="构建未执行：未找到可用编译器或构建文件。",
                    details={"success": False},
                )
            )

    if "binary_runner" in tool_ids and (workspace_dir / "embedded_app").exists():
        completed = subprocess.run(
            "./embedded_app demo-board normal",
            cwd=str(workspace_dir),
            shell=True,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        output = (completed.stdout or completed.stderr or "没有输出").strip()
        results.append(
            ToolExecutionResult(
                tool_id="binary_runner",
                summary=f"二进制运行完成，退出码 {completed.returncode}，输出：{_truncate(output)}",
                details={"success": completed.returncode == 0, "exit_code": completed.returncode, "stdout": output},
            )
        )

    if "acceptance_check" in tool_ids:
        accepted = (
            (workspace_dir / "generated_script.py").exists() and (workspace_dir / "architecture.md").exists()
        ) or (
            (workspace_dir / "embedded_app.c").exists() and (workspace_dir / "embedded_app").exists()
        )
        results.append(
            ToolExecutionResult(
                tool_id="acceptance_check",
                summary="验收检查：基础产物已齐备。" if accepted else "验收检查：基础产物仍不完整。",
                details={"accepted": accepted},
            )
        )

    if "risk_matrix" in tool_ids:
        risk_level = "medium"
        if "失败" in lowered or "风险" in lowered:
            risk_level = "high"
        elif "通过" in lowered or "完成" in lowered:
            risk_level = "low"
        results.append(
            ToolExecutionResult(
                tool_id="risk_matrix",
                summary=f"风险评估等级：{risk_level}。",
                details={"level": risk_level},
            )
        )

    if "device_tree_check" in tool_ids and any(keyword in lowered for keyword in ["设备树", "gpio", "uart", "spi", "i2c", "bsp", "驱动"]):
        results.append(
            ToolExecutionResult(
                tool_id="device_tree_check",
                summary="设备树/BSP 检查建议：确认节点状态、引脚复用、时钟和中断资源是否匹配。",
                details={"checked": True},
            )
        )

    if "serial_log_analyzer" in tool_ids and any(keyword in lowered for keyword in ["日志", "串口", "报错", "异常", "输出", "dmesg"]):
        results.append(
            ToolExecutionResult(
                tool_id="serial_log_analyzer",
                summary="日志分析建议：优先检查退出码、stdout/stderr、串口输出和最近改动的外设初始化路径。",
                details={"analyzed": True},
            )
        )

    if "artifact_packager" in tool_ids:
        packaged = [path.name for path in [workspace_dir / "architecture.md", workspace_dir / "embedded_app.c", workspace_dir / "embedded_app", workspace_dir / "Makefile", workspace_dir / "generated_script.py", workspace_dir / "delivery_note.md"] if path.exists()]
        if packaged:
            results.append(
                ToolExecutionResult(
                    tool_id="artifact_packager",
                    summary=f"交付打包候选产物：{', '.join(packaged)}。",
                    details={"entries": packaged},
                )
            )

    if "remote_sync" in tool_ids and any(keyword in lowered for keyword in ["远端", "部署", "主机", "sync"]):
        results.append(ToolExecutionResult(tool_id="remote_sync", summary="远端同步工具已登记，正式同步仍建议由宿主机脚本执行。", details={"available": True}))

    if "remote_execute" in tool_ids and any(keyword in lowered for keyword in ["远端", "ssh", "执行", "主机"]):
        results.append(ToolExecutionResult(tool_id="remote_execute", summary="远端执行工具已登记，正式命令执行仍建议由宿主机脚本执行。", details={"available": True}))

    if "memory_capture" in tool_ids and any(keyword in lowered for keyword in ["经验", "记录", "沉淀", "记忆"]):
        memory_path = knowledge_dir / "meeting_memory.md"
        with memory_path.open("a", encoding="utf-8") as handle:
            handle.write(f"- {participant_name}: {latest_text}\n")
        results.append(
            ToolExecutionResult(
                tool_id="memory_capture",
                summary="已把本轮信息沉淀到知识记录文件。",
                details={"path": str(memory_path)},
            )
        )

    if "list_knowledge_documents" in tool_ids:
        knowledge_files = sorted(path.name for path in knowledge_dir.iterdir() if path.is_file())
        results.append(
            ToolExecutionResult(
                tool_id="list_knowledge_documents",
                summary=f"知识库文档：{', '.join(knowledge_files) if knowledge_files else '暂无'}。",
                details={"entries": knowledge_files},
            )
        )

    if "read_knowledge_document" in tool_ids:
        target = knowledge_dir / "room_goal.md"
        preview = target.read_text(encoding="utf-8", errors="replace").splitlines()[:10]
        results.append(
            ToolExecutionResult(
                tool_id="read_knowledge_document",
                summary=f"已读取知识文档 {target.name}。",
                details={"path": str(target), "preview": preview},
            )
        )

    if "run_shell_command" in tool_ids and any(keyword in lowered for keyword in ["运行", "执行", "命令", "shell"]):
        script_path = workspace_dir / "generated_script.py"
        command = f'{shlex.quote(sys.executable)} {shlex.quote(str(script_path))}' if script_path.exists() else "cd"
        allowed, reason = _is_command_allowed(command)
        if allowed:
            completed = subprocess.run(
                command,
                cwd=str(workspace_dir),
                shell=True,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            results.append(
                ToolExecutionResult(
                    tool_id="run_shell_command",
                    summary=f"本地命令执行完成，退出码 {completed.returncode}。",
                    details={
                        "command": command,
                        "exit_code": completed.returncode,
                        "stdout": _truncate(completed.stdout or completed.stderr or "没有输出"),
                        "success": completed.returncode == 0,
                    },
                )
            )
        else:
            results.append(ToolExecutionResult(tool_id="run_shell_command", summary=reason, details={"success": False}))

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
                    details={"exit_code": completed.returncode, "stdout": output, "success": completed.returncode == 0},
                )
            )
        else:
            results.append(
                ToolExecutionResult(
                    tool_id="test_runner",
                    summary="测试未执行，因为当前工作目录中还没有 generated_script.py。",
                    details={"success": False},
                )
            )

    if "review_summary" in tool_ids and any(keyword in lowered for keyword in ["结果", "完成", "通过", "测试", "评审"]):
        results.append(
            ToolExecutionResult(
                tool_id="review_summary",
                summary="评审建议：确认目标是否满足、产物是否存在、测试是否通过，再决定继续还是停止讨论。",
                details={"ready_for_review": True},
            )
        )

    if "bug_report" in tool_ids and any(keyword in lowered for keyword in ["失败", "异常", "报错", "bug"]):
        bug_path = workspace_dir / "bug_report.md"
        bug_path.write_text(f"# 缺陷记录\n\n- 现象：{latest_text}\n", encoding="utf-8")
        results.append(
            ToolExecutionResult(
                tool_id="bug_report",
                summary=f"已生成缺陷记录：{bug_path.name}。",
                details={"path": str(bug_path)},
            )
        )

    if "log_summary" in tool_ids:
        log_files = sorted(path.name for path in workspace_dir.glob("*.log"))
        if log_files:
            results.append(
                ToolExecutionResult(
                    tool_id="log_summary",
                    summary=f"日志文件摘要：{', '.join(log_files)}。",
                    details={"entries": log_files},
                )
            )

    if "ssh_execute_command" in tool_ids and any(keyword in lowered for keyword in ["ssh", "远端", "主机"]):
        results.append(
            ToolExecutionResult(
                tool_id="ssh_execute_command",
                summary="SSH 工具已就绪，当前轻量原型仅回传占位信息，正式远端执行建议继续走 systemd/ssh 部署流程。",
                details={"available": True},
            )
        )

    return results


def build_tool_definitions(tool_payloads: list[dict[str, str]]) -> list[ToolDefinition]:
    return [ToolDefinition(**payload) for payload in tool_payloads]