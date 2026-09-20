"""Unit tests for agent/analyzer.py using mock LLM calls."""

from unittest.mock import MagicMock
from agent.analyzer import add_line_numbers, analyze_firmware
from agent.models import FirmwareAnalysis, SpecRule


def test_add_line_numbers():
    """Line numbers are 1-based and correctly formatted."""
    code = "int a = 1;\nint b = 2;\n"
    numbered = add_line_numbers(code)
    lines = numbered.splitlines()
    assert lines[0].strip() == "1: int a = 1;"
    assert lines[1].strip() == "2: int b = 2;"


def test_analyze_firmware_mock(tmp_path):
    """analyze_firmware formats numbered source and returns FirmwareAnalysis."""
    fake_analysis = FirmwareAnalysis(
        summary="Fan controller firmware",
        inputs=["DHT22 pin 2"],
        outputs=["Fan LED pin 13"],
        constants={"THRESHOLD": "30.0"},
        states=["IDLE", "ACTIVE"],
        error_handling=["Sensor fail-safe"],
        communication=["[INFO] BOOT"],
        spec_rules=[
            SpecRule(
                id="R1",
                text="Fan ON when temp >= 30.0",
                source_lines=[44],
                confidence="spec",
            )
        ],
        risk_areas=["Comparison operator > vs >="],
    )

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = fake_analysis.model_dump_json()
    mock_client.models.generate_content.return_value = mock_response

    source = "void setup() {}\nvoid loop() {}"
    result = analyze_firmware(
        source_code=source,
        client=mock_client,
        model="gemini-test",
        cache_dir=tmp_path,
        use_cache=False,
    )

    assert isinstance(result, FirmwareAnalysis)
    assert len(result.spec_rules) == 1
    assert result.spec_rules[0].id == "R1"
    assert result.spec_rules[0].confidence == "spec"

    # Verify that numbered source was in the prompt
    called_prompt = mock_client.models.generate_content.call_args.kwargs["contents"]
    assert "1: void setup() {}" in called_prompt
    assert "2: void loop() {}" in called_prompt
