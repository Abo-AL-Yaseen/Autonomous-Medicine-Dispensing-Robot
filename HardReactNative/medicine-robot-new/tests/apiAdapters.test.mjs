import assert from "node:assert/strict";
import test from "node:test";

import {
  normalizeFastApiHealth,
  normalizeFastApiStatus,
  normalizeMedicine,
  normalizeMission,
  normalizeRoom,
  normalizeRooms,
  normalizeSuccessResponse,
  requireMissionId,
  resolveRobotHardwareStatus,
  unwrapLaravelResource,
} from "../src/services/apiAdapters.ts";

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
