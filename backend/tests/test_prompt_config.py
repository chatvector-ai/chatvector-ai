"""Tests for system prompt loading and LLM generation config wiring."""

import pytest

import services.answer_service as answer_service


def test_load_system_prompt_returns_stripped_content(tmp_path, monkeypatch):
    prompt_file = tmp_path / "custom_system.txt"
    prompt_file.write_text("  line one\nline two  \n", encoding="utf-8")
    monkeypatch.setattr(answer_service.config, "SYSTEM_PROMPT_PATH", str(prompt_file))

    assert answer_service._load_system_prompt() == "line one\nline two"


def test_load_system_prompt_missing_file_raises_clear_file_not_found(tmp_path, monkeypatch):
    missing = tmp_path / "does_not_exist.txt"
    monkeypatch.setattr(answer_service.config, "SYSTEM_PROMPT_PATH", str(missing))

    with pytest.raises(FileNotFoundError) as exc_info:
        answer_service._load_system_prompt()

    msg = str(exc_info.value)
    assert "System prompt file not found" in msg
    assert "SYSTEM_PROMPT_PATH" in msg


@pytest.mark.asyncio
async def test_generate_answer_passes_temperature_and_max_tokens_to_generate_content(
    monkeypatch,
):
    captured: dict = {}

    def fake_generate_content(model, contents, config=None, **kwargs):
        captured["model"] = model
        captured["contents"] = contents
        captured["config"] = config

        class _Result:
            text = "mocked answer"

        return _Result()

    monkeypatch.setattr(answer_service.config, "LLM_TEMPERATURE", 0.7)
    monkeypatch.setattr(answer_service.config, "LLM_MAX_OUTPUT_TOKENS", 512)
    monkeypatch.setattr(
        answer_service.client.models,
        "generate_content",
        fake_generate_content,
    )

    result = await answer_service.generate_answer("What?", "some context")

    assert result == "mocked answer"
    assert captured["model"] == "gemini-2.5-flash"
    assert captured["contents"] == "CONTEXT:\nsome context\n\nQUESTION:\nWhat?"
    cfg = captured["config"]
    assert cfg is not None
    assert cfg.system_instruction == answer_service._SYSTEM_PROMPT
    assert cfg.temperature == 0.7
    assert cfg.max_output_tokens == 512
