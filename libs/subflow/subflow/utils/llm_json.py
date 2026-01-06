"""LLM JSON parsing utilities with Markdown code block support and retry logic."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from subflow.providers.llm import LLMProvider, Message


def parse_llm_json(text: str) -> dict | list:
    """Parse JSON from LLM output, supporting Markdown code blocks.
    
    Handles:
    - Plain JSON
    - ```json ... ``` code blocks
    - ``` ... ``` code blocks
    
    Args:
        text: Raw LLM output text
        
    Returns:
        Parsed JSON as dict or list
        
    Raises:
        json.JSONDecodeError: If JSON parsing fails
    """
    text = text.strip()
    
    # Try to extract Markdown code blocks
    patterns = [
        r'```json\s*([\s\S]*?)\s*```',  # ```json ... ```
        r'```\s*([\s\S]*?)\s*```',       # ``` ... ```
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            text = match.group(1).strip()
            break
    
    # Parse JSON
    return json.loads(text)


@dataclass
class JSONRetryResult:
    """Result of JSON parsing with retry."""
    
    data: dict | list | None
    success: bool
    attempts: int
    last_error: str | None = None


class LLMJSONHelper:
    """Helper for LLM JSON parsing with retry logic."""
    
    MAX_RETRIES = 3
    
    def __init__(self, llm: LLMProvider, max_retries: int = 3):
        """Initialize helper.
        
        Args:
            llm: LLM provider instance
            max_retries: Maximum retry attempts (default 3)
        """
        self.llm = llm
        self.max_retries = max_retries
    
    async def complete_json_with_retry(
        self,
        messages: list[Message],
        temperature: float = 0.3,
    ) -> dict | list:
        """Complete LLM request and parse JSON with retry.
        
        Args:
            messages: Conversation messages
            temperature: LLM temperature
            
        Returns:
            Parsed JSON data
            
        Raises:
            ValueError: If JSON parsing fails after all retries
        """
        current_messages = list(messages)
        last_error: Exception | None = None
        last_response: str = ""
        
        for attempt in range(self.max_retries):
            try:
                response = await self.llm.complete(current_messages, temperature=temperature)
                last_response = response
                return parse_llm_json(response)
            except json.JSONDecodeError as e:
                last_error = e
                
                if attempt < self.max_retries - 1:
                    # Add error feedback for retry
                    current_messages = current_messages + [
                        Message(role="assistant", content=response),
                        Message(
                            role="user",
                            content=(
                                f"JSON 解析失败：{e.msg}（位置 {e.pos}）。\n"
                                "请重新输出有效的 JSON。你可以使用 ```json ... ``` 格式。"
                            ),
                        ),
                    ]
        
        raise ValueError(
            f"JSON 解析失败，已重试 {self.max_retries} 次。\n"
            f"最后错误：{last_error}\n"
            f"最后响应：{last_response[:500]}..."
        )
    
    async def complete_json(
        self,
        messages: list[Message],
        temperature: float = 0.3,
    ) -> dict | list:
        """Alias for complete_json_with_retry."""
        return await self.complete_json_with_retry(messages, temperature)
