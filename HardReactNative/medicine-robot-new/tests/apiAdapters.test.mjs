import assert from "node:assert/strict";
import test from "node:test";

import { getApiErrorCode } from "../src/config/api.ts";
import {
  buildMedicineDispensePayload,
  buildRobotScheduleDateTime,
  normalizeFastApiDispense,
  normalizeMissionExecutorStatus,
  normalizeExecutorStart,
  normalizeFastApiHealth,
  normalizeFastApiStatus,
  normalizeFastApiWaterDispense,
  normalizeFastApiWaterLevel,
  normalizeHardwareActionErrorMessage,
  normalizeMedicine,
  normalizeMission,
  normalizeNavigationStartErrorMessage,
  normalizeRoom,
  normalizeRooms,
  normalizeRobotRtc,
  normalizeSchedulerTick,
  normalizeSuccessResponse,
  requireMissionId,
  robotRtcToLaravelSchedule,
  resolveRobotHardwareStatus,
  unwrapLaravelResource,
} from "../src/services/apiAdapters.ts";
import {
  createPickerWallClockSelection,
  formatApiScheduleSummary,
  formatScheduleDateValue,
  formatScheduleTimeValue,
  isRobotScheduleInPast,
} from "../src/services/scheduleDateTime.ts";

const laravelRoom = {
  id: 7,
  room_number: "A-204",
  room_name: "Cardiology",
  description: null,
  created_at: "2026-08-06T08:00:00Z",
  updated_at: "2026-08-06T08:00:00Z",
};

const laravelMedicine = {
  id: 12,
  name: "Aspirin",
  description: "100 mg tablets",
  stock_quantity: 25,
  created_at: null,
  updated_at: null,
};

test("unwraps a Laravel collection wrapped in data", () => {
  const rooms = normalizeRooms({ data: [laravelRoom] });

  assert.equal(rooms.length, 1);
  assert.equal(rooms[0].id, 7);
});

test("unwraps a single Laravel resource wrapped in data", () => {
  assert.deepEqual(unwrapLaravelResource({ data: laravelRoom }), laravelRoom);
});

test("normalizes Laravel room field names", () => {
  const room = normalizeRoom({ data: laravelRoom });

  assert.deepEqual(
    { id: room.id, number: room.number, name: room.name },
    { id: 7, number: "A-204", name: "Cardiology" },
  );
});

test("normalizes Laravel medicine quantity and optional fields", () => {
  const medicine = normalizeMedicine({ data: laravelMedicine });

  assert.equal(medicine.stock, 25);
  assert.equal(medicine.description, "100 mg tablets");
  assert.equal(medicine.dispenser_box, null);
  assert.equal("dosage" in medicine, false);
});

test("accepts a valid mission ID from a wrapped mission response", () => {
  const mission = normalizeMission({
    data: {
      id: 42,
      room: laravelRoom,
      medicine: laravelMedicine,
      quantity: 2,
      status: "pending",
    },
  });

  assert.equal(requireMissionId(mission.id), 42);
  assert.equal(mission.room_id, 7);
  assert.equal(mission.medicine_id, 12);
});

test("normalizes multiple dynamically supplied mission medicine items", () => {
  const mission = normalizeMission({
    id: 43,
    room: laravelRoom,
    medicine: laravelMedicine,
    quantity: 2,
    status: "pending",
    items: [
      { medicine: laravelMedicine, quantity: 2 },
      {
        medicine: { ...laravelMedicine, id: 13, name: "Ibuprofen", dispenser_box: 2 },
        quantity: 1,
      },
    ],
  });

  assert.deepEqual(
    mission.items.map((item) => [item.medicine_id, item.quantity]),
    [[12, 2], [13, 1]],
  );
});

test("rejects a missing mission ID before navigation can start", () => {
  assert.throws(
    () =>
      normalizeMission({
        data: {
          room: { id: 7 },
          medicine: { id: 12 },
          quantity: 2,
          status: "pending",
        },
      }),
    /missing a valid mission ID.*Navigation was not started/i,
  );
});

test("normalizes FastAPI health when hardware is connected", () => {
  const health = normalizeFastApiHealth({
    status: "running",
    hardware_connected: true,
  });

  assert.equal(health.api_reachable, true);
  assert.equal(health.hardware_connected, true);
  assert.equal(health.connection, "Connected");
});

test("accepts the automatic hand-wait executor state", () => {
  const status = normalizeMissionExecutorStatus({
    state: "WAITING_FOR_HAND",
    mission_id: 42,
    last_error: null,
  });

  assert.equal(status.state, "WAITING_FOR_HAND");
  assert.equal(status.mission_id, 42);
});

test("normalizes FastAPI health when hardware is disconnected", () => {
  const health = normalizeFastApiHealth({
    status: "running",
    hardware_connected: false,
  });

  assert.equal(health.api_reachable, true);
  assert.equal(health.hardware_connected, false);
  assert.equal(health.connection, "Disconnected");
});

test("represents a failed API request separately from disconnection", async () => {
  const result = await resolveRobotHardwareStatus(
    async () => {
      throw new Error("Network error");
    },
    async () => ({ success: true, statuses: {} }),
  );

  assert.equal(result.api_reachable, false);
  assert.equal(result.hardware_connected, false);
  assert.equal(result.connection, "Request Failed");
  assert.equal(result.error, "Network error");
});

test("never treats undefined connection information as connected", () => {
  assert.throws(
    () => normalizeFastApiHealth({ status: "running" }),
    /hardware_connected.*boolean/i,
  );
});

test("normalizes the FastAPI statuses object", () => {
  const health = normalizeFastApiHealth({
    status: "running",
    hardware_connected: true,
  });
  const result = normalizeFastApiStatus(
    {
      success: true,
      statuses: {
        ESP32: "STATUS|MANUAL",
        ARDUINO_UNO: "STATUS|READY",
      },
    },
    health,
  );

  assert.equal(result.connection, "Connected");
  assert.equal(result.statuses.ESP32, "STATUS|MANUAL");
  assert.equal(result.mode, "Manual");
});

test("rejects a Laravel collection with an invalid shape", () => {
  assert.throws(
    () => normalizeRooms({ data: { 0: laravelRoom } }),
    /Invalid rooms response.*array/i,
  );
});

test("normalizes Laravel navigation success responses", () => {
  assert.deepEqual(
    normalizeSuccessResponse({ success: true }, "navigation start"),
    { success: true },
  );
});

test("normalizes navigation start readiness error codes", () => {
  assert.equal(
    normalizeNavigationStartErrorMessage(
      "HARDWARE_UNAVAILABLE",
      "fallback",
    ),
    "Robot hardware is disconnected.",
  );
  assert.equal(
    normalizeNavigationStartErrorMessage(
      "ROBOT_API_UNAVAILABLE",
      "fallback",
    ),
    "Robot service is unavailable.",
  );
  assert.equal(
    normalizeNavigationStartErrorMessage(
      "INVALID_ROBOT_API_RESPONSE",
      "fallback",
    ),
    "Robot service returned an invalid response.",
  );
});

test("extracts a Laravel navigation start error code", () => {
  assert.equal(
    getApiErrorCode({
      isAxiosError: true,
      response: { data: { code: "HARDWARE_UNAVAILABLE" } },
    }),
    "HARDWARE_UNAVAILABLE",
  );
});

test("keeps the fallback for an unknown navigation start error code", () => {
  assert.equal(
    normalizeNavigationStartErrorMessage("UNKNOWN", "fallback"),
    "fallback",
  );
});

test("builds the FastAPI dispense request from the medicine box mapping", () => {
  assert.deepEqual(buildMedicineDispensePayload(1, 2), {
    box1: 2,
    box2: 0,
  });
  assert.deepEqual(buildMedicineDispensePayload(2, 3), {
    box1: 0,
    box2: 3,
  });
});

test("rejects missing or invalid medicine box mappings", () => {
  assert.throws(
    () => buildMedicineDispensePayload(null, 1),
    /valid dispenser box/i,
  );
  assert.throws(
    () => buildMedicineDispensePayload(3, 1),
    /valid dispenser box/i,
  );
});

test("normalizes a successful manual medicine dispense response", () => {
  const result = normalizeFastApiDispense({
    success: true,
    requested: { box1: 2, box2: 0 },
    results: {
      box1: {
        box_number: 1,
        requested_pills: 2,
        dispensed_pills: 2,
      },
    },
  });

  assert.equal(result.results.box1.dispensed_pills, 2);
});

test("normalizes a calibrated water dispense response", () => {
  const result = normalizeFastApiWaterDispense({
    success: true,
    requested_amount_ml: 100,
    delivery_basis: "calibrated_time",
    calibration_ml_per_second: 50,
    duration_ms: 2000,
  });

  assert.equal(result.duration_ms, 2000);
  assert.equal(result.delivery_basis, "calibrated_time");
});

test("normalizes valid and sensor-error water-level responses", () => {
  assert.deepEqual(
    normalizeFastApiWaterLevel({
      success: true,
      distance_cm: 7.3,
      percent: 68,
      status: "OK",
    }),
    { success: true, distance_cm: 7.3, percent: 68, status: "OK" },
  );
  assert.deepEqual(
    normalizeFastApiWaterLevel({
      success: false,
      distance_cm: null,
      percent: null,
      status: "SENSOR_ERROR",
    }),
    { success: false, distance_cm: null, percent: null, status: "SENSOR_ERROR" },
  );
});

test("maps disconnected hardware actions to a clear message", () => {
  assert.equal(
    normalizeHardwareActionErrorMessage(
      "HARDWARE_UNAVAILABLE",
      "fallback",
    ),
    "Hardware Disconnected.",
  );
});

test("builds robot wall-clock schedule text without reading phone time", () => {
  assert.equal(
    buildRobotScheduleDateTime("2026-08-09", "20:30"),
    "2026-08-09 20:30:00",
  );
  assert.throws(
    () => buildRobotScheduleDateTime("2026-02-30", "20:30"),
    /valid scheduled date/i,
  );
});

test("normalizes robot RTC and preserves its wall-clock for Laravel", () => {
  const rtc = normalizeRobotRtc({
    success: true,
    datetime: "2026-08-12T12:30:45",
    source: "DS1302",
    timezone: "Asia/Hebron",
  });

  assert.equal(
    robotRtcToLaravelSchedule(rtc.datetime),
    "2026-08-12 12:30:45",
  );
});

test("normalizes scheduler and executor confirmations", () => {
  const ready = normalizeSchedulerTick({
    success: true,
    result: "READY_FOR_EXECUTION",
    mission_id: 42,
    message: null,
    executor: {
      state: "READY_FOR_EXECUTION",
      mission_id: 42,
      last_error: null,
    },
  });
  const started = normalizeExecutorStart({
    success: true,
    result: "STARTED",
    message: null,
    executor: {
      state: "GOING_TO_ROOM",
      mission_id: 42,
      last_error: null,
    },
  });

  assert.equal(ready.executor.state, "READY_FOR_EXECUTION");
  assert.equal(started.executor.state, "GOING_TO_ROOM");
});

test("rejects an unknown executor state instead of assuming movement", () => {
  assert.throws(
    () =>
      normalizeExecutorStart({
        success: true,
        result: "STARTED",
        message: null,
        executor: {
          state: "MOVING_MAYBE",
          mission_id: 42,
          last_error: null,
        },
      }),
    /unsupported executor state/i,
  );
});

test("formats picker selections as the existing Laravel schedule format", () => {
  const dateSelection = createPickerWallClockSelection(
    new Date("2026-08-09T10:00:00.000Z"),
    120,
  );
  const timeSelection = createPickerWallClockSelection(
    new Date("2026-08-09T18:52:00.000Z"),
    120,
  );
  const date = formatScheduleDateValue(dateSelection);
  const time = formatScheduleTimeValue(timeSelection);

  assert.equal(date, "2026-08-09");
  assert.equal(time, "20:52");
  assert.equal(
    buildRobotScheduleDateTime(date, time),
    "2026-08-09 20:52:00",
  );
});

test("does not apply the Palestine timezone twice to picker wall-clock fields", () => {
  const nativeSelection = createPickerWallClockSelection(
    new Date("2026-08-09T18:52:00.000Z"),
    120,
  );
  const oldReinterpretedTime = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Hebron",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(nativeSelection.value);

  assert.equal(oldReinterpretedTime, "21:52");
  assert.equal(formatScheduleTimeValue(nativeSelection), "20:52");
});

test("displays a UTC API timestamp in Palestine local time", () => {
  assert.equal(
    formatApiScheduleSummary(
      "2026-08-09T17:52:00+00:00",
      "Asia/Hebron",
      "en-US",
    ),
    "Aug 9, 2026 • 8:52 PM",
  );
});

test("rejects an elapsed minute using Asia/Hebron robot time", () => {
  const dateSelection = createPickerWallClockSelection(
    new Date("2026-08-09T09:00:00.000Z"),
    180,
  );
  const elapsedTime = createPickerWallClockSelection(
    new Date("2026-08-09T17:30:00.000Z"),
    180,
  );
  const futureTime = createPickerWallClockSelection(
    new Date("2026-08-09T17:32:00.000Z"),
    180,
  );
  const now = new Date("2026-08-09T17:31:15.000Z");

  assert.equal(
    isRobotScheduleInPast(
      dateSelection,
      elapsedTime,
      "Asia/Hebron",
      now,
    ),
    true,
  );
  assert.equal(
    isRobotScheduleInPast(
      dateSelection,
      futureTime,
      "Asia/Hebron",
      now,
    ),
    false,
  );
});
