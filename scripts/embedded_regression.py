from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    workspace = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(workspace / "src"))
    os.environ["AMR_DISABLE_LLM"] = "1"

    from agent_meeting_room.models import TaskStatus
    from agent_meeting_room.services import MeetingRoomService

    base_dir = Path(tempfile.mkdtemp(prefix="amr-embedded-", dir=str(workspace)))
    service = MeetingRoomService(base_dir / "embedded.db")

    scenarios = [
        {
            "name": "board_info",
            "goal": "编写一个嵌入式 Linux 用户态 C 程序，打印板卡信息并输出运行状态。",
            "task": "实现板卡信息打印工具",
            "message": "请以嵌入式 Linux 方式完成一个 C 程序，先做架构设计，再生成源码、Makefile、编译并运行，最终输出 status=embedded-linux-demo-ok。",
            "seed_broken": False,
        },
        {
            "name": "gpio_diag_repair",
            "goal": "编写一个 GPIO 诊断程序，并确保修复后可以成功构建运行。",
            "task": "实现 GPIO 诊断程序",
            "message": "请先完成架构设计，再实现一个嵌入式 Linux GPIO 诊断小程序。即使当前源码有问题，也要持续修复直到编译和运行成功。",
            "seed_broken": True,
        },
        {
            "name": "uart_tool",
            "goal": "编写一个 UART 调试演示程序，并通过测试和评审。",
            "task": "实现 UART 调试演示程序",
            "message": "请先完成架构设计，再实现一个嵌入式 Linux UART 调试工具，要求生成程序、构建、运行并通过评审验收。",
            "seed_broken": False,
        },
    ]

    for scenario in scenarios:
        room = service.create_room(f"回归-{scenario['name']}", scenario["goal"], seed_defaults=True)
        participants = service.list_participants(room.room_id)
        owner = next(participant for participant in participants if "开发" in participant.role)
        task = service.add_task(
            room_id=room.room_id,
            title=scenario["task"],
            description=scenario["goal"],
            owner_id=owner.participant_id,
            acceptance_criteria="必须生成源码、Makefile、可执行文件，程序运行输出 status=embedded-linux-demo-ok，并被评审通过。",
        )

        room_workspace = service.role_store.workspace_dir(room.room_id)
        if scenario["seed_broken"]:
            (room_workspace / "embedded_app.c").write_text(
                "int main(void) { return missing_symbol; }\n",
                encoding="utf-8",
            )

        latest_message = service.post_message(room.room_id, "p1", scenario["message"])
        generated = service.drive_room_to_completion(room.room_id, latest_message, max_cycles=8)
        state = service.get_state(room.room_id)
        decisions = service.list_decisions(room.room_id)
        current_task = service.get_task(room.room_id, task.task_id)

        required_paths = [
            room_workspace / "architecture.md",
            room_workspace / "embedded_app.c",
            room_workspace / "Makefile",
            room_workspace / "embedded_app",
        ]
        missing = [path.name for path in required_paths if not path.exists()]
        if missing:
            raise AssertionError(f"{scenario['name']} 缺少产物: {missing}")
        if current_task.status not in {TaskStatus.APPROVED, TaskStatus.DONE}:
            raise AssertionError(f"{scenario['name']} 任务未闭环: {current_task.status.value}")
        if not decisions or not decisions[0].approved:
            raise AssertionError(f"{scenario['name']} 未形成通过评审")

        run_result = subprocess.run(
            "./embedded_app demo-board normal",
            cwd=str(room_workspace),
            shell=True,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        output = (run_result.stdout or run_result.stderr or "").strip()
        if run_result.returncode != 0 or "status=embedded-linux-demo-ok" not in output:
            raise AssertionError(f"{scenario['name']} 程序运行结果不符合预期: exit={run_result.returncode}, output={output}")

        senders = " -> ".join(message.sender_name for message in generated)
        print(f"SCENARIO={scenario['name']}")
        print(f"TASK_STATUS={current_task.status.value}")
        print(f"SENDERS={senders}")
        print(f"RUN_OUTPUT={output}")
        print("---")


if __name__ == "__main__":
    main()