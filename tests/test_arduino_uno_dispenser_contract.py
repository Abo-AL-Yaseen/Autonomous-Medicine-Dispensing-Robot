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


def test_pill_sensors_match_the_verified_physical_box_to_chute_mapping() -> None:
    source = sketch_source()

    assert "const byte PILL_SENSOR_1_PIN = 3;" in source
    assert "const byte PILL_SENSOR_2_PIN = 12;" in source
    assert "&motor1,\n      PILL_SENSOR_1_PIN," in source
    assert "&motor2,\n      PILL_SENSOR_2_PIN," in source
    assert "Stepper motor1(STEPS_PER_REV, 4, 6, 5, 7);" in source
    assert "Stepper motor2(STEPS_PER_REV, 8, 10, 9, 11);" in source


def test_confirmed_dispense_keeps_256_incremental_steps_and_sensor_errors() -> None:
    source = sketch_source()

    assert "#define SLOT_COUNT 8" in source
    assert "#define STEPS_PER_SLOT (STEPS_PER_REV / SLOT_COUNT)" in source
    assert "#define PILL_STEPS STEPS_PER_SLOT" in source
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
    pcint0 = source[source.index("ISR(PCINT0_vect)"):source.index("ISR(PCINT2_vect)")]
    pcint2 = source[source.index("ISR(PCINT2_vect)"):source.index("void resetPillIrqDebug()")]
    assert "&pillSensor2Capture" in pcint0
    assert "&pillSensor1Capture" in pcint2


def test_valid_pin_change_pulse_latches_once_and_short_pulse_is_ignored() -> None:
    source = sketch_source()

    assert "volatile bool armed;" in source
    assert "volatile bool lowActive;" in source
    assert "volatile bool pulseLatched;" in source
    assert "volatile unsigned long lowStartedAtMicros;" in source
    assert "pulseWidth >= PILL_MIN_PULSE_US" in source
    assert "capture->pulseLatched = true;" in source
    assert "capture->armed = false;" in source
    assert "if (!capture->armed || capture->pulseLatched)" in source


def test_temporary_irq_debug_reports_all_pcint_and_per_sensor_capture_state() -> None:
    source = sketch_source()

    assert 'strcmp(command, "GET_PILL_IRQ_DEBUG")' in source
    assert 'F("PILL_IRQ_DEBUG|PCINT0=")' in source
    for field in (
        "PCINT2",
        "D12_FALL",
        "D12_RISE",
        "D3_FALL",
        "D3_RISE",
        "ARM1",
        "ARM2",
        "ARMED1",
        "ARMED2",
        "LATCH1",
        "LATCH2",
        "LAST_US1",
        "LAST_US2",
        "PCICR",
        "PCMSK0",
        "PCMSK2",
        "PCIFR",
        "DDRD",
        "PIND",
    ):
        assert f'F("|{field}=")' in source
    assert "pcint0InvocationCount++" in source
    assert "pcint2InvocationCount++" in source
    assert "pillSensor1FallingEdgeCount++" in source
    assert "pillSensor1RisingEdgeCount++" in source
    assert "pillSensor2FallingEdgeCount++" in source
    assert "pillSensor2RisingEdgeCount++" in source
    assert "Serial" not in source[source.index("ISR(PCINT0_vect)"):source.index("void resetPillIrqDebug()")]


def test_irq_debug_is_reset_at_the_start_of_each_dispense_command() -> None:
    source = sketch_source()

    dispense_1 = source.index('strcmp(command, "DISPENSE_1")')
    dispense_2 = source.index('strcmp(command, "DISPENSE_2")')
    both = source.index('strcmp(command, "DISPENSE_BOTH")')
    assert "resetPillIrqDebug();" in source[dispense_1:dispense_2]
    assert "resetPillIrqDebug();" in source[dispense_2:both]
    assert "resetPillIrqDebug();" in source[both:]


def test_atmega328p_d3_uses_pcint19_bit_three_in_pcint_group_two() -> None:
    source = sketch_source()

    assert "const byte PILL_SENSOR_1_PIN = 3;" in source
    assert "(PIND & _BV(PD3)) == LOW" in source
    assert "PCMSK2 |= _BV(PCINT19);" in source
    assert "PCICR |= _BV(PCIE0) | _BV(PCIE2);" in source
    assert "PCIFR |= _BV(PCIF0) | _BV(PCIF2);" in source
    assert "ISR(PCINT2_vect)" in source


def test_atmega328p_d12_remains_box_two_pcint4_in_group_zero() -> None:
    source = sketch_source()

    assert "const byte PILL_SENSOR_2_PIN = 12;" in source
    assert "(PINB & _BV(PB4)) == LOW" in source
    assert "PCMSK0 |= _BV(PCINT4);" in source
    assert "ISR(PCINT0_vect)" in source


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


def test_manual_slot_calibration_is_required_and_never_moves_a_motor() -> None:
    source = sketch_source()

    assert "bool disk1Calibrated = false;" in source
    assert "bool disk2Calibrated = false;" in source
    assert 'strcmp(command, "SET_SLOT_ZERO_1")' in source
    assert 'strcmp(command, "SET_SLOT_ZERO_2")' in source
    assert 'Serial.println(F("ACK|SET_SLOT_ZERO_1"));' in source
    assert 'Serial.println(F("ACK|SET_SLOT_ZERO_2"));' in source
    assert "DISK_NOT_CALIBRATED" in source
    calibration = source[source.index('strcmp(command, "SET_SLOT_ZERO_1")'):source.index('strcmp(command, "DISPENSE_1")')]
    assert "step(" not in calibration


def test_slot_position_advances_after_the_physical_motor_move_even_on_timeout() -> None:
    source = sketch_source()

    movement = source[source.index("for (int step = 0; step < PILL_STEPS; step++)"):source.index("if (!pillPulseLatched(sensorPin))")]
    assert "advanceDiskSlot(currentSlot);" in movement
    assert "*currentSlot = (*currentSlot + 1) % SLOT_COUNT;" in source
    assert 'strcmp(command, "GET_DISK_STATUS")' in source
    assert "DISK1_CALIBRATED" in source
    assert "DISK2_CALIBRATED" in source
