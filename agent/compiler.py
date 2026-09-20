"""Scenario compiler: TestCase -> Wokwi YAML scenario and diagram variants."""

from pathlib import Path
import json
import re
import shutil
import yaml
from agent.models import TestCase


class SingleQuotedStr(str):
    """Custom string wrapper to force single-quote representation in PyYAML."""

    pass


class CustomSafeDumper(yaml.SafeDumper):
    """Safe YAML dumper that quotes SingleQuotedStr scalars."""

    pass


CustomSafeDumper.add_representer(
    SingleQuotedStr,
    lambda dumper, data: dumper.represent_scalar(
        "tag:yaml.org,2002:str", data, style="'"
    ),
)


def _extract_temp_from_expectation(text: str) -> float | None:
    """Extract temperature value from expectation string containing 'temp=<x.x>'."""
    match = re.search(r"temp=([0-9\.\-]+)", text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def _format_step_value(temp: float) -> int | float:
    """Format temperature value: use int if whole number, otherwise float."""
    if temp.is_integer():
        return int(temp)
    return temp


def compile_test(
    test: TestCase,
    project_dir: Path | str,
    out_dir: Path | str,
) -> Path:
    """Compile a TestCase into a runnable Wokwi scenario directory.

    Writes into out_dir:
    - wokwi.toml: points to firmware.hex and firmware.elf
    - diagram.json: copied from project_dir (or modified if sensor == 'disconnected')
    - scenario.test.yaml: generated scenario adhering to pairing rules

    Returns:
        Path to the generated scenario.test.yaml.
    """
    project_path = Path(project_dir).resolve()
    target_out_dir = Path(out_dir).resolve()
    target_out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Write wokwi.toml
    wokwi_toml_path = target_out_dir / "wokwi.toml"
    wokwi_toml_content = (
        "[wokwi]\nversion = 1\nfirmware = 'firmware.hex'\nelf = 'firmware.elf'\n"
    )
    wokwi_toml_path.write_text(wokwi_toml_content, encoding="utf-8")

    # 2. Write diagram.json (modified for sensor == 'disconnected')
    src_diagram = project_path / "diagram.json"
    dest_diagram = target_out_dir / "diagram.json"

    if src_diagram.is_file():
        diagram_data = json.loads(src_diagram.read_text(encoding="utf-8"))
        if test.sensor == "disconnected":
            # Remove all connections that contain "dht1:SDA"
            conns = diagram_data.get("connections", [])
            filtered_conns = [
                c
                for c in conns
                if not any("dht1:SDA" in str(endpoint) for endpoint in c)
            ]
            diagram_data["connections"] = filtered_conns
        dest_diagram.write_text(
            json.dumps(diagram_data, indent=2), encoding="utf-8"
        )
    else:
        # If diagram.json not found in project_path, create a minimal fallback
        dest_diagram.write_text("{}", encoding="utf-8")

    # 3. Generate steps for scenario.test.yaml
    steps_list: list[dict] = [
        {"wait-serial": SingleQuotedStr("[INFO] BOOT")}
    ]

    if test.sensor == "disconnected":
        # Disconnected: Skip all set-control steps, only wait for expectations
        for exp in test.expect:
            steps_list.append(
                {"wait-serial": SingleQuotedStr(exp.serial_contains)}
            )
    else:
        pending_steps = list(test.steps)
        for exp in test.expect:
            target_temp = _extract_temp_from_expectation(exp.serial_contains)

            if target_temp is not None:
                # Expectation contains "temp=X"
                # First emit all not-yet-applied steps up to and including the first pending step with set_temp == X
                match_idx = None
                for idx, st in enumerate(pending_steps):
                    if (
                        st.set_temp is not None
                        and abs(st.set_temp - target_temp) < 0.05
                    ):
                        match_idx = idx
                        break

                if match_idx is not None:
                    # Emit steps up to and including match_idx
                    for st in pending_steps[: match_idx + 1]:
                        if st.set_temp is not None:
                            steps_list.append(
                                {
                                    "set-control": {
                                        "part-id": SingleQuotedStr("dht1"),
                                        "control": SingleQuotedStr(
                                            "temperature"
                                        ),
                                        "value": _format_step_value(
                                            st.set_temp
                                        ),
                                    }
                                }
                            )
                    pending_steps = pending_steps[match_idx + 1 :]
            else:
                # Expectation has no "temp=" (e.g. "[ALARM] OVERHEAT")
                # Apply next pending step if any
                if pending_steps:
                    st = pending_steps.pop(0)
                    if st.set_temp is not None:
                        steps_list.append(
                            {
                                "set-control": {
                                    "part-id": SingleQuotedStr("dht1"),
                                    "control": SingleQuotedStr("temperature"),
                                    "value": _format_step_value(st.set_temp),
                                }
                            }
                        )

            # Then emit its wait-serial
            steps_list.append(
                {"wait-serial": SingleQuotedStr(exp.serial_contains)}
            )

        # Apply any leftover steps at the end
        for st in pending_steps:
            if st.set_temp is not None:
                steps_list.append(
                    {
                        "set-control": {
                            "part-id": SingleQuotedStr("dht1"),
                            "control": SingleQuotedStr("temperature"),
                            "value": _format_step_value(st.set_temp),
                        }
                    }
                )

    # 4. Dump YAML
    scenario_dict = {
        "name": SingleQuotedStr(test.name),
        "version": 1,
        "steps": steps_list,
    }

    yaml_output = yaml.dump(
        scenario_dict,
        Dumper=CustomSafeDumper,
        sort_keys=False,
    )
    scenario_path = target_out_dir / "scenario.test.yaml"
    scenario_path.write_text(yaml_output, encoding="utf-8")

    return scenario_path
