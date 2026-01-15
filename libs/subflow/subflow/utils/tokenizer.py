"""Token counting and text truncation utilities."""

from __future__ import annotations

from typing import cast


def count_tokens(text: str, encoding_name: str = "cl100k_base") -> int:
    """Count tokens in text using tiktoken.

    Falls back to character-based estimation if tiktoken is not available.

    Args:
        text: Text to count tokens for
        encoding_name: Tiktoken encoding name (default: cl100k_base for GPT-4)

    Returns:
        Estimated token count
    """
    try:
        import tiktoken

        enc = tiktoken.get_encoding(encoding_name)
        return len(enc.encode(text))
    except ImportError:
        # Fallback: estimate based on characters
        # English: ~4 chars/token, Chinese: ~1.5 chars/token
        # Use a conservative estimate of 2 chars/token
        return len(text) // 2


def truncate_to_tokens(
    text: str,
    max_tokens: int,
    encoding_name: str = "cl100k_base",
    strategy: str = "sample",
) -> str:
    """Truncate text to fit within token limit.

    Args:
        text: Text to truncate
        max_tokens: Maximum token count
        encoding_name: Tiktoken encoding name
        strategy: Truncation strategy
            - "sample": Keep beginning + middle + end (default)
            - "head": Keep only beginning
            - "tail": Keep only end

    Returns:
        Truncated text within token limit
    """
    try:
        import tiktoken

        enc = tiktoken.get_encoding(encoding_name)
        tokens = enc.encode(text)

        if len(tokens) <= max_tokens:
            return text

        if strategy == "head":
            return cast(str, enc.decode(tokens[:max_tokens]))
        elif strategy == "tail":
            return cast(str, enc.decode(tokens[-max_tokens:]))
        else:  # sample
            # Split into 3 parts: beginning, middle, end
            part_size = max_tokens // 3
            remainder = max_tokens - part_size * 3

            begin = tokens[: part_size + remainder]
            mid_start = len(tokens) // 2 - part_size // 2
            middle = tokens[mid_start : mid_start + part_size]
            end = tokens[-part_size:]

            # Decode each part and join with separator
            begin_text = cast(str, enc.decode(begin))
            middle_text = cast(str, enc.decode(middle))
            end_text = cast(str, enc.decode(end))

            return f"{begin_text}\n\n[...中间省略...]\n\n{middle_text}\n\n[...中间省略...]\n\n{end_text}"

    except ImportError:
        # Fallback: character-based truncation
        max_chars = max_tokens * 2  # Conservative estimate

        if len(text) <= max_chars:
            return text

        if strategy == "head":
            return text[:max_chars]
        elif strategy == "tail":
            return text[-max_chars:]
        else:  # sample
            part_size = max_chars // 3
            begin = text[:part_size]
            middle = text[len(text) // 2 - part_size // 2 : len(text) // 2 + part_size // 2]
            end = text[-part_size:]
            return f"{begin}\n\n[...中间省略...]\n\n{middle}\n\n[...中间省略...]\n\n{end}"


def estimate_prompt_tokens(
    system_prompt: str,
    user_content: str,
    encoding_name: str = "cl100k_base",
) -> int:
    """Estimate total tokens for a prompt.

    Includes overhead for message formatting.

    Args:
        system_prompt: System message content
        user_content: User message content
        encoding_name: Tiktoken encoding name

    Returns:
        Estimated total token count
    """
    # Add ~10 tokens overhead for message formatting
    overhead = 10
    return (
        count_tokens(system_prompt, encoding_name)
        + count_tokens(user_content, encoding_name)
        + overhead
    )
