# LLM Pass 2 Optimization: Replace-Only Correction

## Overview

Optimize LLM Pass 2 to use a simplified correction approach where the LLM only outputs correction pairs instead of full corrected text. This reduces token usage and simplifies the output format while focusing only on homophone errors.

## Changes Required

### 1. Update `libs/subflow/subflow/stages/llm_passes.py`

#### 1.1 Update System Prompt in `SemanticChunkingPass._get_system_prompt()`

**Current behavior**: Prompt asks for full corrected text in `corrected_segments.text`

**New behavior**: 
- Remove `text` field from `corrected_segments` in the JSON example
- Change rule 2) from "修正明显识别错误（谐音字、断句错误、重复词、漏字）" to "**仅修正谐音字错误**，不修正断句错误、重复词、漏字等其他问题"
- Add explanation that `corrected_segments` is optional and can be omitted when there are no errors

Lines to modify: approximately 114-153

#### 1.2 Update `SemanticChunkingPass._parse_result()` method

**Current behavior**: Expects `corrected_segments[].text` field and uses it directly

**New behavior**:
- Make `corrected_segments` parsing optional (handle None/missing)
- Generate corrected text by applying string replacements from `corrections` array to original ASR segment text
- Need access to original ASR segment text to apply replacements

Lines to modify: approximately 185-256

Add a helper function:
```python
def _apply_corrections(original_text: str, corrections: list[Correction]) -> str:
    """Apply corrections to original ASR text via string replacement."""
    result = original_text
    for corr in corrections:
        result = result.replace(corr.original, corr.corrected)
    return result
```

Modify `_parse_result` to:
1. Accept original ASR segments as parameter (or get text from context)
2. Handle `corrected_segments` being None, missing, or empty
3. For each correction item, get original text from ASR segment and apply corrections

#### 1.3 Update `SemanticChunkingPass.execute()` method

Pass the ASR segments window to `_parse_result()` so it can look up original text for applying corrections.

Lines to modify: approximately 330-335

### 2. Update Tests

#### 2.1 Update `apps/worker/tests/test_semantic_chunking_pass_parse_result.py`

**Current test**: Expects `text` field in `corrected_segments`

**New test cases needed**:
1. Test with corrections only (no text field) - should apply replacements
2. Test with empty `corrected_segments` array
3. Test with missing `corrected_segments` key entirely
4. Test with no corrections in a segment

## Verification Plan

### Automated Tests

Run the existing test to ensure backward compatibility is not broken:
```bash
cd /home/zji/SubFlow
uv run --directory apps/worker pytest apps/worker/tests/test_semantic_chunking_pass_parse_result.py -v
```

After implementing the new test cases, run:
```bash
cd /home/zji/SubFlow
uv run --directory apps/worker pytest apps/worker/tests/ -v
```

### Manual Test Cases

Test the following scenarios manually if automated tests are not sufficient:

1. **Correction with homophone error**: 
   - Input: `{"corrected_segments": [{"asr_segment_id": 0, "corrections": [{"original": "人工只能", "corrected": "人工智能"}]}]}`
   - Original ASR text: "我们今天聊人工只能"
   - Expected corrected text: "我们今天聊人工智能"

2. **No corrections needed**:
   - Input: `{"chunk": {...}, "next_cursor": 2}` (no corrected_segments key)
   - Should parse successfully without errors

3. **Empty corrections array**:
   - Input: `{"corrected_segments": [], "chunk": {...}, "next_cursor": 2}`
   - Should parse successfully, corrected_map should be empty

## Implementation Notes

- The `_parse_result` method signature needs to change to accept original ASR segment data
- Use `dict.get("corrected_segments", []) or []` pattern for safe access
- When `corrections` list is empty, the corrected text should be the same as original
- Maintain backward compatibility: if `text` field is present, use it as fallback
