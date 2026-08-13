"""Static contract checks for the Arduino UNO pill-confirmation sketch.

The repository has no Arduino simulator; these tests protect the pin mapping,
incremental movement, and machine-readable protocol consumed by Raspberry.
"""

from pathlib import Path


SKETCH = (
    Path(__file__).parents[1]
    / "arduino_controller"
    / "medicine_dispenser_uno"
    / "medicine_dispenser_uno"
    / "medicine_dispenser_uno.ino"
)


def sketch_source() -> str:
    return SKETCH.read_text(encoding="utf-8")


def test_pill_sensors_are_mapped_only_to_the_audited_uno_pins() -> None:
    source = sketch_source()

    assert "const byte PILL_SENSOR_1_PIN = 12;" in source
    assert "const byte PILL_SENSOR_2_PIN = 3;" in source
    assert "&motor1,\n      PILL_SENSOR_1_PIN," in source
    assert "&motor2,\n      PILL_SENSOR_2_PIN," in source
    assert "Stepper motor1(STEPS_PER_REV, 4, 6, 5, 7);" in source
    assert "Stepper motor2(STEPS_PER_REV, 8, 10, 9, 11);" in source


def test_confirmed_dispense_keeps_256_incremental_steps_and_sensor_errors() -> None:
    source = sketch_source()

    assert "#define PILL_STEPS 256" in source
    assert "for (int step = 0; step < PILL_STEPS; step++)" in source
    assert "motor->step(1);" in source
    assert "PILL_DETECT_DEBOUNCE_MS = 1" in source
    assert "PILL_CLEAR_DEBOUNCE_MS = 10" in source
    assert "PILL_DETECTION_TIMEOUT_MS = 2000" in source
    assert "ERROR|" in source
    assert "SENSOR_STUCK" in source
    assert "PILL_TIMEOUT" in source
    assert "DONE|DISPENSE_1" in source
    assert "DONE|DISPENSE_2" in source


def test_dispense_both_uses_the_same_sensor_confirmed_path() -> None:
    source = sketch_source()

    assert source.count("runConfirmedPill(") >= 5
    assert "ERROR|DISPENSE_BOTH|BOX=" in source
    assert "printDispenseBothError(1, firstResult);" in source
    assert "printDispenseBothError(2, secondResult);" in source


def test_temporary_raw_pill_sensor_diagnostics_do_not_use_dispense_helpers() -> None:
    source = sketch_source()

    assert 'strcmp(command, "GET_PILL_SENSORS")' in source
    assert 'strcmp(command, "MONITOR_PILL_SENSORS")' in source
    assert 'F("PILL_SENSORS|D12=")' in source
    assert 'F("|D3=")' in source
    assert 'F("PILL_SENSOR|PIN=")' in source
    assert "PILL_SENSOR_MONITOR_MS = 5000" in source
