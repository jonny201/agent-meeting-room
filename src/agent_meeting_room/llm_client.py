from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from openai import OpenAI

from .models import LLMProfile


logger = logging.getLogger(__name__)


class LLMClient:
    """OpenAI-compatible client used by role agents."""

    def __init__(self, profile: LLMProfile) -> None:
        self.profile = profile
        httpx_client = httpx.Client(verify=True, trust_env=False, timeout=180.0)
        self.client = OpenAI(
            api_key=profile.api_key,
            base_url=profile.base_url,
            http_client=httpx_client,
        )

    def call(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": self.profile.model,
            "messages": messages,
            "temperature": self.profile.temperature,
            "max_tokens": self.profile.max_tokens,
            "stream": False,
        }

        if self.profile.enable_thinking:
            params["extra_body"] = {"enable_thinking": True}

        try:
            response = self.client.chat.completions.create(**params)
            choice = response.choices[0]
            message = choice.message
            return {
                "success": True,
                "content": message.content or "",
                "thinking_content": getattr(message, "reasoning_content", "") or "",
                "finish_reason": choice.finish_reason,
                "usage": {
                    "prompt_tokens": getattr(response.usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(response.usage, "completion_tokens", 0),
                    "total_tokens": getattr(response.usage, "total_tokens", 0),
                },
            }
        except Exception as exc:
            logger.exception("LLM call failed for profile %s", self.profile.profile_id)
            return {
                "success": False,
                "content": "",
                "thinking_content": "",
                "finish_reason": "error",
                "usage": {},
                "error": str(exc),
            }

    def dump_request(self, messages: list[dict[str, Any]]) -> str:
        return json.dumps(messages, ensure_ascii=False, indent=2)