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
        "WATER_DISPENSING",
        "MEDICINE_READY",
        "NO_HAND",
        "DISPENSE_FAILED",
    ):
        assert f'"{state}"' in firmware
    assert 'Serial.print("ACK|LCD|STATE=");' in firmware
    assert 'lcdShowStatus("Take a cup", "Place under water", "Place hand below", "Waiting...");' in firmware
    assert 'lcdShowStatus("Dispensing medicine", "Please wait");' in firmware
    assert 'lcdShowStatus("Dispensing water", "Please wait");' in firmware
    assert 'lcdShowStatus("Medicine & water", "ready");' in firmware
    assert '"Take med & water"' in firmware
    assert 'String("Returning in: ") + String(secondsRemaining)' in firmware
    assert 'normalizedCommand.startsWith("LCD|STATE=PICKUP_WAITING|SECONDS=")' in firmware
    assert "startLineFollowing();" not in firmware[
        firmware.index('normalizedCommand == "GET_HAND"'):
        firmware.index('normalizedCommand == "GET_HAND"') + 1200
    ]


def test_timed_water_path_always_turns_pump_off_before_completion() -> None:
    firmware = source()
    start = firmware.index("void runPumpForDuration(unsigned long durationMs) {")
    end = firmware.index("//", start)
    timed_water = firmware[start:end]

    assert "pumpOn();" in timed_water
    assert "bool completed = waitSafely(durationMs);" in timed_water
    assert "pumpOff();" in timed_water
    assert timed_water.index("pumpOff();") < timed_water.index(
        'Serial.print("DONE|WATER|DURATION_MS=");'
    )


def test_serial_parser_dispatches_only_complete_single_character_legacy_lines() -> None:
    firmware = source()
    parser = firmware[
        firmware.index("static SerialInputResult readSerialInput"):
        firmware.index("static bool interruptionRequested()")
    ]
    dispatcher = firmware[
        firmware.index("static void processSerialInput()"):
        firmware.index("void setup()")
    ]

    assert "Every command is newline-terminated" in firmware
    assert "if (incoming == '\\n')" in parser
    assert "if (isLegacyCommand(incoming))" not in parser
    assert "serialPending" not in parser
    assert (
        "receivedLine.length() == 1 && isLegacyCommand(receivedLine.charAt(0))"
        in dispatcher
    )


def test_lcd_lines_and_unknown_long_l_or_r_lines_cannot_dispatch_legacy_turns() -> None:
    firmware = source()
    dispatcher = firmware[
        firmware.index("static void processSerialInput()"):
        firmware.index("void setup()")
    ]
    text_handler = firmware[
        firmware.index("void handleTextCommand"):
        firmware.index("static void processSerialInput()")
    ]

    assert dispatcher.count("handleLegacyCommand(") == 1
    assert "else {\n      handleTextCommand(receivedLine);\n    }" in dispatcher
    assert 'Serial.println("ERROR|UNKNOWN_COMMAND");' in text_handler

    assert 'case \'L\':' in firmware
    assert 'Serial.println("ACK|LEFT");' in firmware
    assert 'case \'R\':' in firmware
    assert 'Serial.println("ACK|RIGHT");' in firmware
