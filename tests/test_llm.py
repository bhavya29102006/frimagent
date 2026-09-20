"""Unit tests for agent/llm.py using mock clients."""

from unittest.mock import MagicMock
import hashlib
import json
import pytest
from pydantic import BaseModel, ValidationError

from agent.llm import generate_json, get_gemini_config


class DummyModel(BaseModel):
    ok: bool
    name: str = "default"


class AnotherModel(BaseModel):
    ok: bool
    count: int = 0


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch):
    """Prevent load_dotenv from overriding monkeypatched environment variables."""
    monkeypatch.setattr("agent.llm.load_dotenv", lambda *args, **kwargs: None)


class MockResponse:

    def __init__(self, text: str):
        self.text = text


def test_missing_api_key_raises_error(monkeypatch):
    """When GEMINI_API_KEY is not set, get_gemini_config raises ValueError."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="GEMINI_API_KEY is not set"):
        get_gemini_config()


def test_generate_json_success(tmp_path):
    """generate_json parses valid JSON response into schema_model and injects schema into prompt."""
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = MockResponse(
        '{"ok": true, "name": "firmagent"}'
    )

    result = generate_json(
        prompt="Say hello",
        schema_model=DummyModel,
        client=mock_client,
        model="gemini-test",
        cache_dir=tmp_path,
        use_cache=True,
    )

    assert isinstance(result, DummyModel)
    assert result.ok is True
    assert result.name == "firmagent"
    assert mock_client.models.generate_content.call_count == 1

    # Verify prompt contains schema instructions and no response_schema in config
    call_args = mock_client.models.generate_content.call_args
    prompt_sent = call_args.kwargs["contents"]
    config_sent = call_args.kwargs["config"]

    assert (
        "Return ONLY valid JSON matching this schema. No markdown." in prompt_sent
    )
    assert '"ok"' in prompt_sent
    assert config_sent.response_mime_type == "application/json"
    assert getattr(config_sent, "response_schema", None) is None


def test_generate_json_fenced_markdown_stripped(tmp_path):
    """Markdown code fences (```json ... ```) are cleanly stripped."""
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = MockResponse(
        "```json\n{\n  \"ok\": true,\n  \"name\": \"fenced_test\"\n}\n```"
    )

    result = generate_json(
        prompt="Fenced test",
        schema_model=DummyModel,
        client=mock_client,
        model="gemini-test",
        cache_dir=tmp_path,
        use_cache=False,
    )

    assert result.ok is True
    assert result.name == "fenced_test"


def test_generate_json_invalid_then_valid_repair(tmp_path):
    """When first response returns invalid JSON, repair retry passes validation error and succeeds."""
    mock_client = MagicMock()
    # 1st attempt: invalid JSON missing 'ok'
    # 2nd attempt: fenced valid JSON
    mock_client.models.generate_content.side_effect = [
        MockResponse('```json\n{"wrong_field": "bad"}\n```'),
        MockResponse('```json\n{"ok": true, "name": "repaired_success"}\n```'),
    ]

    result = generate_json(
        prompt="Repair prompt test",
        schema_model=DummyModel,
        client=mock_client,
        model="gemini-test",
        cache_dir=tmp_path,
        use_cache=False,
    )

    assert result.ok is True
    assert result.name == "repaired_success"
    assert mock_client.models.generate_content.call_count == 2

    second_prompt = (
        mock_client.models.generate_content.call_args_list[1].kwargs["contents"]
    )
    assert "VALIDATION ERROR" in second_prompt
    assert "PREVIOUS ATTEMPT OUTPUT" in second_prompt
    assert "wrong_field" in second_prompt


def test_generate_json_disk_cache_includes_schema_key(tmp_path):
    """Cache key distinguishes between different schemas for the same prompt."""
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = [
        MockResponse('{"ok": true, "name": "first_schema"}'),
        MockResponse('{"ok": true, "count": 42}'),
    ]

    # Call with DummyModel
    res1 = generate_json(
        prompt="Common prompt",
        schema_model=DummyModel,
        client=mock_client,
        model="gemini-test",
        cache_dir=tmp_path,
        use_cache=True,
    )
    assert res1.name == "first_schema"
    assert mock_client.models.generate_content.call_count == 1

    # Call again with same prompt and DummyModel -> hits cache
    res1_cached = generate_json(
        prompt="Common prompt",
        schema_model=DummyModel,
        client=mock_client,
        model="gemini-test",
        cache_dir=tmp_path,
        use_cache=True,
    )
    assert res1_cached.name == "first_schema"
    assert mock_client.models.generate_content.call_count == 1

    # Call with same prompt but AnotherModel -> does NOT hit cache for DummyModel
    res2 = generate_json(
        prompt="Common prompt",
        schema_model=AnotherModel,
        client=mock_client,
        model="gemini-test",
        cache_dir=tmp_path,
        use_cache=True,
    )
    assert res2.count == 42
    assert mock_client.models.generate_content.call_count == 2


def test_generate_json_rate_limit_backoff(tmp_path, monkeypatch):
    """When rate limit (429) occurs, backoff retries the call."""
    mock_client = MagicMock()

    class RateLimitError(Exception):
        code = 429

    mock_client.models.generate_content.side_effect = [
        RateLimitError("Resource has been exhausted (e.g. check quota)"),
        MockResponse('{"ok": true, "name": "after_backoff"}'),
    ]

    monkeypatch.setattr("time.sleep", lambda s: None)

    result = generate_json(
        prompt="Backoff prompt",
        schema_model=DummyModel,
        client=mock_client,
        model="gemini-test",
        cache_dir=tmp_path,
        use_cache=False,
    )

    assert result.ok is True
    assert result.name == "after_backoff"
    assert mock_client.models.generate_content.call_count == 2


def test_retry_on_503_then_success(tmp_path, monkeypatch, capsys):
    """When client fails twice with 503, backoff retries with delays (2s, 4s) and succeeds on 3rd attempt."""
    mock_client = MagicMock()

    class ServiceUnavailableError(Exception):
        code = 503

    mock_client.models.generate_content.side_effect = [
        ServiceUnavailableError("Service Unavailable (503)"),
        ServiceUnavailableError("Service Unavailable (503)"),
        MockResponse('{"ok": true, "name": "success_after_503"}'),
    ]

    sleep_delays = []
    monkeypatch.setattr("time.sleep", lambda s: sleep_delays.append(s))

    result = generate_json(
        prompt="Retry 503 prompt",
        schema_model=DummyModel,
        client=mock_client,
        model="gemini-test",
        cache_dir=tmp_path,
        use_cache=False,
    )

    assert result.ok is True
    assert result.name == "success_after_503"
    assert mock_client.models.generate_content.call_count == 3
    assert sleep_delays == [2, 4]

    captured = capsys.readouterr()
    assert "Gemini busy, retry 2/5 in 2s" in captured.out
    assert "Gemini busy, retry 3/5 in 4s" in captured.out


def test_fallback_model_switch_after_3_failures(tmp_path, monkeypatch):
    """Switches to GEMINI_FALLBACK_MODEL after 3 failed attempts."""
    mock_client = MagicMock()

    class ServiceUnavailableError(Exception):
        code = 503

    mock_client.models.generate_content.side_effect = [
        ServiceUnavailableError("503 error 1"),
        ServiceUnavailableError("503 error 2"),
        ServiceUnavailableError("503 error 3"),
        MockResponse('{"ok": true, "name": "fallback_model_ok"}'),
    ]

    monkeypatch.setenv("GEMINI_FALLBACK_MODEL", "gemini-fallback-flash")
    monkeypatch.setattr("time.sleep", lambda s: None)

    result = generate_json(
        prompt="Fallback prompt",
        schema_model=DummyModel,
        client=mock_client,
        model="gemini-primary",
        cache_dir=tmp_path,
        use_cache=False,
    )

    assert result.ok is True
    assert result.name == "fallback_model_ok"
    assert mock_client.models.generate_content.call_count == 4

    calls = mock_client.models.generate_content.call_args_list
    assert calls[0].kwargs["model"] == "gemini-primary"
    assert calls[1].kwargs["model"] == "gemini-primary"
    assert calls[2].kwargs["model"] == "gemini-primary"
    assert calls[3].kwargs["model"] == "gemini-fallback-flash"


def test_cache_works_offline_without_api_key(tmp_path, monkeypatch):
    """Cached response works without GEMINI_API_KEY and without network access."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    prompt = "Offline cached prompt"
    schema_key_str = json.dumps(DummyModel.model_json_schema(), sort_keys=True)
    cache_payload = f"{prompt}\n{schema_key_str}"
    prompt_hash = hashlib.sha256(cache_payload.encode("utf-8")).hexdigest()
    cache_file = tmp_path / f"{prompt_hash}.json"
    cache_file.write_text('{"ok": true, "name": "offline_cached"}', encoding="utf-8")

    result = generate_json(
        prompt=prompt,
        schema_model=DummyModel,
        client=None,
        cache_dir=tmp_path,
        use_cache=True,
    )

    assert result.ok is True
    assert result.name == "offline_cached"
