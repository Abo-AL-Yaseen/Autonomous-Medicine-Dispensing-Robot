"""Static contracts for ESP32-owned ultrasonic water-level monitoring."""

from pathlib import Path


SOURCE = Path(__file__).parents[1] / "esp32_controller" / "src" / "main.cpp"


def source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_water_level_uses_the_existing_hc_sr04_pins_and_calibration_constants() -> None:
    firmware = source()

    assert "const int ULTRASONIC_TRIG_PIN = 18;" in firmware
    assert "const int ULTRASONIC_ECHO_PIN = 34;" in firmware
    assert "const float WATER_FULL_DISTANCE_CM = 5.0f;" in firmware
    assert "const float WATER_EMPTY_DISTANCE_CM = 25.0f;" in firmware
    assert "int waterLevelPercentForDistance(float distanceCm)" in firmware
    assert "if (distanceCm <= WATER_FULL_DISTANCE_CM) return 100;" in firmware
    assert "if (distanceCm >= WATER_EMPTY_DISTANCE_CM) return 0;" in firmware
    assert "return constrain(roundedPercent, 0, 100);" in firmware


def test_water_level_formula_clamps_full_empty_and_middle_distances() -> None:
    full_distance_cm = 5.0
    empty_distance_cm = 25.0

    def percent(distance_cm: float) -> int:
        if distance_cm <= full_distance_cm:
            return 100
        if distance_cm >= empty_distance_cm:
            return 0
        return round(
            100
            * (empty_distance_cm - distance_cm)
            / (empty_distance_cm - full_distance_cm)
        )

    assert percent(4.0) == 100
    assert percent(5.0) == 100
    assert percent(15.0) == 50
    assert percent(25.0) == 0
    assert percent(30.0) == 0


def test_water_level_protocol_reports_valid_readings_and_sensor_errors() -> None:
    firmware = source()

    assert 'normalizedCommand == "GET_WATER_LEVEL"' in firmware
    assert 'Serial.print("WATER_LEVEL|DISTANCE_CM=");' in firmware
    assert 'Serial.println("WATER_LEVEL|DISTANCE_CM=NA|PERCENT=NA|STATUS=SENSOR_ERROR");' in firmware
    assert "const uint8_t WATER_LOW_PERCENT = 20;" in firmware
    assert "const uint8_t WATER_EMPTY_PERCENT = 5;" in firmware
    assert 'return "LOW";' in firmware
    assert 'return "EMPTY";' in firmware


def test_legacy_ultrasonic_obstacle_mode_cannot_drive_from_water_distance() -> None:
    firmware = source()
    legacy_handler = firmware[
        firmware.index("void handleLegacyCommand"):
        firmware.index("static void prepareManualDrive")
    ]

    assert "case 'A':" in legacy_handler
    assert 'Serial.println("ERROR|AUTONOMOUS_MODE_DISABLED");' in legacy_handler
    assert "startAutonomousMode();" not in legacy_handler
