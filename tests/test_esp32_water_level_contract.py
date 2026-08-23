"""Static contracts for ESP32-owned ultrasonic water-level monitoring."""

from pathlib import Path


SOURCE = Path(__file__).parents[1] / "esp32_controller" / "src" / "main.cpp"


def source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_water_level_uses_the_existing_hc_sr04_pins_and_calibration_constants() -> None:
    firmware = source()

    assert "const int ULTRASONIC_TRIG_PIN = 18;" in firmware
    assert "const int ULTRASONIC_ECHO_PIN = 34;" in firmware
    assert "const float WATER_FULL_DISTANCE_CM = 2.3f;" in firmware
    assert "const float WATER_EMPTY_DISTANCE_CM = 6.9f;" in firmware
    assert "int waterLevelPercentForDistance(float distanceCm)" in firmware
    assert "if (distanceCm <= WATER_FULL_DISTANCE_CM) return 100;" in firmware
    assert "if (distanceCm >= WATER_EMPTY_DISTANCE_CM) return 0;" in firmware
    assert "return constrain(roundedPercent, 0, 100);" in firmware


def test_water_level_formula_clamps_full_empty_and_middle_distances() -> None:
    full_distance_cm = 2.3
    empty_distance_cm = 6.9

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

    assert percent(2.0) == 100
    assert percent(2.3) == 100
    assert percent(3.45) == 75
    assert percent(4.6) == 50
    assert percent(5.75) == 25
    assert percent(6.9) == 0
    assert percent(8.0) == 0


def test_water_level_protocol_reports_valid_readings_and_sensor_errors() -> None:
    firmware = source()

    assert 'normalizedCommand == "GET_WATER_LEVEL"' in firmware
    assert 'Serial.print("WATER_LEVEL|DISTANCE_CM=");' in firmware
    assert 'Serial.println("WATER_LEVEL|DISTANCE_CM=NA|PERCENT=NA|STATUS=SENSOR_ERROR");' in firmware
    assert "const uint8_t WATER_LOW_PERCENT = 20;" in firmware
    assert "const uint8_t WATER_EMPTY_PERCENT = 5;" in firmware
    assert 'return "LOW";' in firmware
    assert 'return "EMPTY";' in firmware


def test_water_level_collects_two_valid_readings_with_spaced_bounded_retries() -> None:
    firmware = source()
    sampling_start = firmware.index("float readWaterLevelDistanceCm() {")
    sampling = firmware[
        sampling_start:
        firmware.index(
            "int waterLevelPercentForDistance(float distanceCm) {",
            sampling_start,
        )
    ]

    assert "const uint8_t WATER_LEVEL_SAMPLE_COUNT = 2;" in firmware
    assert "const uint8_t WATER_LEVEL_MAX_ATTEMPTS = 4;" in firmware
    assert "const unsigned long WATER_LEVEL_PING_INTERVAL_MS = 60;" in firmware
    assert "attempt < WATER_LEVEL_MAX_ATTEMPTS" in sampling
    assert "delay(WATER_LEVEL_PING_INTERVAL_MS);" in sampling
    assert "if (distance >= 0.0f)" in sampling
    assert "if (validReadings == WATER_LEVEL_SAMPLE_COUNT)" in sampling
    assert "if (validReadings != WATER_LEVEL_SAMPLE_COUNT)" in sampling


def test_legacy_ultrasonic_obstacle_mode_cannot_drive_from_water_distance() -> None:
    firmware = source()
    legacy_handler = firmware[
        firmware.index("void handleLegacyCommand"):
        firmware.index("static void prepareManualDrive")
    ]

    assert "case 'A':" in legacy_handler
    assert 'Serial.println("ERROR|AUTONOMOUS_MODE_DISABLED");' in legacy_handler
    assert "startAutonomousMode();" not in legacy_handler
