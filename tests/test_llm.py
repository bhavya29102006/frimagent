"""Unit tests for agent/llm.py using mock clients."""

from unittest.mock import MagicMock
import hashlib
import pytest
from pydantic import BaseModel, ValidationError

from agent.llm import generate_json, get_gemini_config


class DummyModel(BaseModel):
    ok: bool
    name: str = "default"


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
    """generate_json parses valid JSON response into schema_model."""
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


def test_generate_json_disk_cache_hit(tmp_path):
    """Subsequent call with identical prompt hits disk cache and avoids LLM call."""
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = MockResponse(
        '{"ok": true, "name": "cached_run"}'
    )

    # First call: populates cache
    res1 = generate_json(
        prompt="Cache test prompt",
        schema_model=DummyModel,
        client=mock_client,
        model="gemini-test",
        cache_dir=tmp_path,
        use_cache=True,
    )
    assert res1.name == "cached_run"
    assert mock_client.models.generate_content.call_count == 1

    # Second call: should hit cache
    res2 = generate_json(
        prompt="Cache test prompt",
        schema_model=DummyModel,
        client=mock_client,
        model="gemini-test",
        cache_dir=tmp_path,
        use_cache=True,
    )
    assert res2.name == "cached_run"
    # Call count remains 1 because cache was hit
    assert mock_client.models.generate_content.call_count == 1


def test_generate_json_repair_retry(tmp_path):
    """When first response fails validation, one repair retry is attempted with the error."""
    mock_client = MagicMock()
    # 1st attempt: invalid (missing required 'ok' field)
    # 2nd attempt: valid
    mock_client.models.generate_content.side_effect = [
        MockResponse('{"invalid_field": 123}'),
        MockResponse('{"ok": true, "name": "repaired"}'),
    ]

    result = generate_json(
        prompt="Generate dummy",
        schema_model=DummyModel,
        client=mock_client,
        model="gemini-test",
        cache_dir=tmp_path,
        use_cache=False,
    )

    assert result.ok is True
    assert result.name == "repaired"
    assert mock_client.models.generate_content.call_count == 2

    # Verify repair prompt contained previous output and error
    second_call_prompt = (
        mock_client.models.generate_content.call_args_list[1].kwargs["contents"]
    )
    assert "VALIDATION ERROR" in second_call_prompt
    assert "PREVIOUS ATTEMPT OUTPUT" in second_call_prompt


def test_generate_json_rate_limit_backoff(tmp_path, monkeypatch):
    """When rate limit (429) occurs, backoff retries the call."""
    mock_client = MagicMock()

    class RateLimitError(Exception):
        code = 429

    mock_client.models.generate_content.side_effect = [
        RateLimitError("Resource has been exhausted (e.g. check quota)"),
        MockResponse('{"ok": true, "name": "after_backoff"}'),
    ]

    # Speed up sleep during tests
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
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
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
