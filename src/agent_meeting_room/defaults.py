from __future__ import annotations

from .models import ParticipantType


DEFAULT_ROOM = {
    "room_name": "默认会议室",
    "goal": "通过 AI 角色与真人协作完成需求讨论、脚本编写、测试执行、结果评审和长期知识沉淀。",
}


DEFAULT_TOOLS = [
    {"tool_id": "task_breakdown", "name": "任务拆解", "description": "把需求拆成任务和验收点。", "category": "planning"},
    {"tool_id": "architecture_design", "name": "架构草案", "description": "在工作目录中生成架构草案。", "category": "design"},
    {"tool_id": "code_writer", "name": "代码草案", "description": "在工作目录中生成 Python 脚本草案。", "category": "execution"},
    {"tool_id": "artifact_reader", "name": "产物检查", "description": "读取当前会议室工作目录中的已有产物。", "category": "analysis"},
    {"tool_id": "test_runner", "name": "测试执行", "description": "尝试运行工作目录中的脚本并回传结果。", "category": "execution"},
    {"tool_id": "review_summary", "name": "评审总结", "description": "根据讨论和测试结果形成评审结论。", "category": "review"},
    {"tool_id": "question_router", "name": "相关性判断", "description": "判断当前消息是否与自己相关。", "category": "analysis"},
]


DEFAULT_LLM_PROFILES = [
    {
        "profile_id": "level1",
        "name": "qwen3-235b-a22b-thinking-2507",
        "provider": "iflow",
        "model": "qwen3-235b-a22b-thinking-2507",
        "base_url": "https://apis.iflow.cn/v1",
        "api_key": "sk-108578bf2396a9c396cc5cb1b973e834",
        "temperature": 0.0,
        "max_tokens": 131072,
        "enable_thinking": True,
        "is_default": True,
    },
    {
        "profile_id": "level2",
        "name": "qwen3-235b-a22b-instruct",
        "provider": "iflow",
        "model": "qwen3-235b-a22b-instruct",
        "base_url": "https://apis.iflow.cn/v1",
        "api_key": "sk-108578bf2396a9c396cc5cb1b973e834",
        "temperature": 0.0,
        "max_tokens": 131072,
        "enable_thinking": True,
        "is_default": False,
    },
    {
        "profile_id": "level3",
        "name": "DeepSeek-V3",
        "provider": "siliconflow",
        "model": "Pro/deepseek-ai/DeepSeek-V3.2",
        "base_url": "https://api.siliconflow.cn/v1",
        "api_key": "sk-icdjqxvbjfzptcpexcpxwksqodfufnsqwhasqwvwzouwhrwm",
        "temperature": 0.1,
        "max_tokens": 163840,
        "enable_thinking": True,
        "is_default": False,
    },
    {
        "profile_id": "level4",
        "name": "DeepSeek-V3 Stable",
        "provider": "siliconflow",
        "model": "Pro/deepseek-ai/DeepSeek-V3.2",
        "base_url": "https://api.siliconflow.cn/v1",
        "api_key": "sk-icdjqxvbjfzptcpexcpxwksqodfufnsqwhasqwvwzouwhrwm",
        "temperature": 0.0,
        "max_tokens": 163840,
        "enable_thinking": True,
        "is_default": False,
    },
    {
        "profile_id": "level5",
        "name": "Qwen3-8B",
        "provider": "siliconflow",
        "model": "Qwen/Qwen3-8B",
        "base_url": "https://api.siliconflow.cn/v1",
        "api_key": "sk-icdjqxvbjfzptcpexcpxwksqodfufnsqwhasqwvwzouwhrwm",
        "temperature": 0.1,
        "max_tokens": 131072,
        "enable_thinking": True,
        "is_default": False,
    },
]


DEFAULT_PARTICIPANTS = [
    {
        "participant_id": "p1",
        "name": "主持人",
        "role": "主持人",
        "participant_type": ParticipantType.HUMAN.value,
        "description": "组织讨论、发起需求、控制暂停和停止。",
        "enabled": True,
        "llm_profile_id": "",
        "tools": ["task_breakdown"],
        "system_prompt": "你是会议主持人，需要让讨论聚焦、及时叫停无效争论、明确下一步。",
    },
    {
        "participant_id": "p2",
        "name": "架构师Agent",
        "role": "架构师Agent",
        "participant_type": ParticipantType.AI.value,
        "description": "关注模块边界、分层设计、技术风险和软件框架。",
        "enabled": True,
        "llm_profile_id": "level1",
        "tools": ["question_router", "task_breakdown", "architecture_design", "artifact_reader"],
        "system_prompt": "你是架构师。只有当消息与你的职责相关时才回复。输出聚焦于模块划分、接口、目录结构和关键风险。",
    },
    {
        "participant_id": "p3",
        "name": "开发Agent",
        "role": "开发Agent",
        "participant_type": ParticipantType.AI.value,
        "description": "关注代码实现、脚本生成、工程结构和执行效率。",
        "enabled": True,
        "llm_profile_id": "level2",
        "tools": ["question_router", "artifact_reader", "code_writer"],
        "system_prompt": "你是开发 Agent。只有在需要编码、补代码、解释实现或回应测试问题时才回复。",
    },
    {
        "participant_id": "p4",
        "name": "测试Agent",
        "role": "测试Agent",
        "participant_type": ParticipantType.AI.value,
        "description": "关注测试时机、执行过程、结果回传、边界条件和回归风险。",
        "enabled": True,
        "llm_profile_id": "level5",
        "tools": ["question_router", "artifact_reader", "test_runner", "review_summary"],
        "system_prompt": "你是测试 Agent。代码未完成时尽量少发言，只在测试准备、测试执行、结果分析相关时回复。",
    },
    {
        "participant_id": "p5",
        "name": "产品专家Agent",
        "role": "产品专家Agent",
        "participant_type": ParticipantType.AI.value,
        "description": "关注需求边界、业务流程和验收口径。",
        "enabled": True,
        "llm_profile_id": "level3",
        "tools": ["question_router", "task_breakdown", "review_summary"],
        "system_prompt": "你是产品专家。只在需求澄清、验收口径、用户价值相关时回复。",
    },
    {
        "participant_id": "p6",
        "name": "评审Agent",
        "role": "评审Agent",
        "participant_type": ParticipantType.AI.value,
        "description": "关注产出是否满足目标，负责形成是否继续推进的判断。",
        "enabled": True,
        "llm_profile_id": "level4",
        "tools": ["question_router", "artifact_reader", "review_summary"],
        "system_prompt": "你是评审 Agent。只在阶段收口、测试结果、质量判断相关时回复。",
    },
]


DEFAULT_MEMORIES = [
    {
        "title": "协作原则",
        "content": "优先把目标拆成清晰任务，每轮讨论都尽量给出下一步行动和验收标准。",
        "tags": "workflow,planning,review",
        "source": "seed",
    }
]