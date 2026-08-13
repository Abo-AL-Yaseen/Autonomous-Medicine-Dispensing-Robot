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
    assert "PILL_MIN_PULSE_US = 200" in source
    assert "PILL_CLEAR_DEBOUNCE_MS = 10" in source
    assert "PILL_DETECTION_TIMEOUT_MS = 2000" in source
    assert "ERROR|" in source
    assert "SENSOR_STUCK" in source
    assert "PILL_TIMEOUT" in source
    assert "DONE|DISPENSE_1" in source
    assert "DONE|DISPENSE_2" in source


def test_both_pill_sensors_use_their_avr_pin_change_interrupt_groups() -> None:
    source = sketch_source()

    assert "ISR(PCINT0_vect)" in source
    assert "(PINB & _BV(PB4)) == LOW" in source
    assert "ISR(PCINT2_vect)" in source
    assert "(PIND & _BV(PD3)) == LOW" in source
    assert "PCMSK0 |= _BV(PCINT4);" in source
    assert "PCMSK2 |= _BV(PCINT19);" in source
    assert "PCICR |= _BV(PCIE0) | _BV(PCIE2);" in source


def test_valid_pin_change_pulse_latches_once_and_short_pulse_is_ignored() -> None:
    source = sketch_source()

    assert "volatile bool armed;" in source
    assert "volatile bool lowActive;" in source
    assert "volatile bool pulseLatched;" in source
    assert "volatile unsigned long lowStartedAtMicros;" in source
    assert "now - capture->lowStartedAtMicros >= PILL_MIN_PULSE_US" in source
    assert "capture->pulseLatched = true;" in source
    assert "capture->armed = false;" in source
    assert "if (!capture->armed || capture->pulseLatched)" in source


def test_dispense_arms_only_its_sensor_and_uses_the_isr_latch_during_motion() -> None:
    source = sketch_source()

    arm_index = source.index("armPillSensorCapture(sensorPin);")
    step_index = source.index("for (int step = 0; step < PILL_STEPS; step++)")
    latch_wait_index = source.index("while (!pillPulseLatched(sensorPin)")
    assert arm_index < step_index < latch_wait_index
    assert "while (!pillPulseLatched(sensorPin)" in source
    assert "if (!pillPulseLatched(sensorPin))" in source
    assert "disarmPillSensorCapture(sensorPin);" in source


def test_existing_per_box_ack_done_and_error_protocol_is_preserved() -> None:
    source = sketch_source()

    assert 'Serial.println(F("ACK|DISPENSE_1"));' in source
    assert 'Serial.println(F("ACK|DISPENSE_2"));' in source
    assert 'Serial.println(F("DONE|DISPENSE_1"));' in source
    assert 'Serial.println(F("DONE|DISPENSE_2"));' in source
    assert 'Serial.println(F("DONE|DISPENSE_BOTH"));' in source
    assert 'Serial.print(F("ERROR|"));' in source


def test_sensor_starts_blocked_and_sensor_must_clear_before_done() -> None:
    source = sketch_source()

    assert "if (pillSensorDetected(sensorPin))" in source
    assert "return DISPENSE_SENSOR_STUCK;" in source
    assert source.count("PILL_CLEAR_DEBOUNCE_MS") >= 3
    assert source.count("waitForStableSensorState(") >= 3


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
