"""Static contracts for the ESP32-owned hand sensor and LCD workflow."""

from pathlib import Path


SOURCE = (
    Path(__file__).parents[1] / "esp32_controller" / "src" / "main.cpp"
)


def source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_hand_sensor_uses_the_existing_gpio16_active_low_debounced_path() -> None:
    firmware = source()

    assert "const int IR_SENSOR_PIN = 16;" in firmware
    assert "const int IR_DETECTED_LEVEL = LOW;" in firmware
    assert "const unsigned long IR_DEBOUNCE_MS = 100;" in firmware
    assert "irCurrentRawDetected = digitalRead(IR_SENSOR_PIN) == IR_DETECTED_LEVEL;" in firmware
    assert 'Serial.println("IR|HAND_DETECTED");' in firmware


def test_hand_and_lcd_commands_are_machine_readable_and_do_not_touch_navigation() -> None:
    firmware = source()

    assert 'normalizedCommand == "GET_HAND"' in firmware
    assert '"HAND|DETECTED"' in firmware
    assert '"HAND|WAITING"' in firmware
    assert 'normalizedCommand.startsWith("LCD|STATE=")' in firmware
    for state in (
        "HAND_WAITING",
        "HAND_DETECTED",
        "DISPENSING",
        "MEDICINE_READY",
        "NO_HAND",
        "DISPENSE_FAILED",
    ):
        assert f'"{state}"' in firmware
    assert 'Serial.print("ACK|LCD|STATE=");' in firmware
    assert "startLineFollowing();" not in firmware[
        firmware.index('normalizedCommand == "GET_HAND"'):
        firmware.index('normalizedCommand == "GET_HAND"') + 1200
    ]
