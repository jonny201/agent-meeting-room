from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def main() -> None:
    workspace = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(workspace / "src"))
    os.environ["AMR_DISABLE_LLM"] = "1"

    from agent_meeting_room.services import MeetingRoomService

    base_dir = Path(tempfile.mkdtemp(prefix="amr-smoke-", dir=str(workspace)))
    service = MeetingRoomService(base_dir / "smoke.db")

    room1 = service.create_room("链路闭环测试", "完成架构、实现、测试、评审并收口。", seed_defaults=True)
    msg1 = service.post_message(room1.room_id, "p1", "请先完成架构设计和代码实现，然后运行测试并判断是否可以收口。")
    chain1 = service.trigger_ai_discussion(room1.room_id, msg1)

    room2 = service.create_room("失败回退测试", "验证测试失败后会回退给开发。", seed_defaults=True)
    workspace2 = service.role_store.workspace_dir(room2.room_id)
    (workspace2 / "generated_script.py").write_text(
        "from __future__ import annotations\n\nraise SystemExit(1)\n",
        encoding="utf-8",
    )
    msg2 = service.post_message(room2.room_id, "p1", "请测试当前脚本运行结果，如果失败就让开发继续修复。")
    chain2 = service.trigger_ai_discussion(room2.room_id, msg2, max_rounds=3)

    room3 = service.create_room("主持人收口测试", "当所有事情都完成后交给主持人决定。", seed_defaults=True)
    msg3 = service.post_message(room3.room_id, "p1", "当前任务已经完成并通过评审，请确认是否可以收口。")
    chain3 = service.trigger_ai_discussion(room3.room_id, msg3, max_rounds=2)

    scenarios = [
        ("normal_chain", chain1),
        ("failure_handoff", chain2),
        ("moderator_handoff", chain3),
    ]
    for name, chain in scenarios:
        print(f"SCENARIO={name}")
        print("SENDERS=" + " -> ".join(message.sender_name for message in chain))
        for index, message in enumerate(chain, start=1):
            print(f"MESSAGE_{index}={message.sender_name}:{message.content}")
        print("---")


if __name__ == "__main__":
    main()