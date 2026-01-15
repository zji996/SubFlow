import pytest

from subflow.utils.subprocess import run_subprocess


@pytest.mark.asyncio
async def test_run_subprocess_executes_command() -> None:
    result = await run_subprocess(["bash", "-lc", "echo -n hi"])
    assert result.returncode == 0
    assert result.stdout == b"hi"
