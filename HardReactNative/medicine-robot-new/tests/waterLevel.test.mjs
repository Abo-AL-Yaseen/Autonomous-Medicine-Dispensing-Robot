import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { robotApiBaseUrl } from "../src/config/api.ts";
import {
  getMissionReadyWaterLevel,
  waterLevelDisplay,
  waterLevelMissionError,
} from "../src/services/robot/waterLevelService.ts";

test("water level service uses the configured shared robot API URL", () => {
  const service = readFileSync(
    new URL("../src/services/robot/waterLevelService.ts", import.meta.url),
    "utf8",
  );

  assert.match(service, /robotApi/);
  assert.match(service, /robotApi\.get<unknown>\("\/water\/level"\)/);
  assert.doesNotMatch(service, /https?:\/\//);
  assert.match(robotApiBaseUrl, /^https?:\/\//);
});

test("water level display shows normal, low, empty, and unavailable states", () => {
  assert.deepEqual(
    waterLevelDisplay({ success: true, distance_cm: 7.3, percent: 68, status: "OK" }),
    { value: "68%", status: "OK", warning: null },
  );
  assert.deepEqual(
    waterLevelDisplay({ success: true, distance_cm: 20, percent: 20, status: "LOW" }),
    { value: "20%", status: "Low", warning: "Water level is low." },
  );
  assert.deepEqual(
    waterLevelDisplay({ success: true, distance_cm: 25, percent: 0, status: "EMPTY" }),
    { value: "0%", status: "Empty", warning: "Water tank is empty." },
  );
  assert.deepEqual(
    waterLevelDisplay({ success: false, distance_cm: null, percent: null, status: "SENSOR_ERROR" }),
    { value: "N/A", status: "Sensor Error", warning: "Water-level sensor unavailable." },
  );
});

test("manual control renders the water-level card and status warning", () => {
  const screen = readFileSync(
    new URL("../src/screens/ManualControlScreen.tsx", import.meta.url),
    "utf8",
  );

  assert.match(screen, /label="Water Level"/);
  assert.match(screen, /Water Status:/);
  assert.match(screen, /displayedWaterLevel\.warning/);
});

test("mission readiness blocks empty and sensor errors but allows low water", () => {
  assert.equal(
    waterLevelMissionError({
      success: true,
      distance_cm: 6.9,
      percent: 0,
      status: "EMPTY",
    }),
    "Water tank is empty. Fill it before starting delivery.",
  );
  assert.equal(
    waterLevelMissionError({
      success: false,
      distance_cm: null,
      percent: null,
      status: "SENSOR_ERROR",
    }),
    "Unable to verify the water level. Check the ultrasonic sensor.",
  );
  assert.equal(
    waterLevelMissionError({
      success: true,
      distance_cm: 5.5,
      percent: 20,
      status: "LOW",
    }),
    null,
  );
  assert.equal(
    waterLevelMissionError({
      success: true,
      distance_cm: 2.3,
      percent: 100,
      status: "OK",
    }),
    null,
  );
});

test("fresh preflight blocks mission creation for empty, sensor, and API failure", async () => {
  let createCalls = 0;
  const attemptMissionCreation = async (loadWaterLevel) => {
    await getMissionReadyWaterLevel(loadWaterLevel);
    createCalls += 1;
  };

  await assert.rejects(
    attemptMissionCreation(async () => ({
      success: true,
      distance_cm: 6.9,
      percent: 0,
      status: "EMPTY",
    })),
    /Water tank is empty\. Fill it before starting delivery\./,
  );
  await assert.rejects(
    attemptMissionCreation(async () => ({
      success: false,
      distance_cm: null,
      percent: null,
      status: "SENSOR_ERROR",
    })),
    /Unable to verify the water level\. Check the ultrasonic sensor\./,
  );
  await assert.rejects(
    attemptMissionCreation(async () => {
      throw new Error("request unavailable");
    }),
    /Unable to verify the water level\. Check the ultrasonic sensor\./,
  );

  assert.equal(createCalls, 0);
});

test("fresh low-water preflight keeps its warning but permits mission creation", async () => {
  let createCalls = 0;
  const level = await getMissionReadyWaterLevel(async () => ({
    success: true,
    distance_cm: 5.5,
    percent: 20,
    status: "LOW",
  }));
  createCalls += 1;

  assert.equal(level.status, "LOW");
  assert.equal(waterLevelDisplay(level).warning, "Water level is low.");
  assert.equal(createCalls, 1);
});

test("delivery screen renders fresh water readiness before mission controls", () => {
  const screen = readFileSync(
    new URL("../src/screens/DeliveryScreen.tsx", import.meta.url),
    "utf8",
  );

  assert.match(screen, /<Text style={styles\.waterTankTitle}>Water Tank<\/Text>/);
  assert.match(screen, /displayedWaterLevel\.value/);
  assert.match(screen, /waterLevel\.distance_cm} cm/);
  assert.match(screen, /{waterLevelStatus}/);
  assert.match(screen, /Last refresh:/);
  assert.match(screen, /waterLevelStatus === "LOW"/);
  assert.match(screen, /waterLevelStatusColor/);
  assert.match(screen, /void refreshWaterLevel\(\)\.catch/);

  const waterCard = screen.indexOf("styles.waterTankCard");
  const missionControls = screen.indexOf("<RoomSelector");
  assert.ok(waterCard >= 0 && waterCard < missionControls);
});

test("immediate submission awaits a fresh water reading before creation/start", () => {
  const screen = readFileSync(
    new URL("../src/screens/DeliveryScreen.tsx", import.meta.url),
    "utf8",
  );
  const payloadIndex = screen.indexOf("const payload =");
  const preflightIndex = screen.indexOf(
    "await verifyImmediateWaterReadiness()",
    payloadIndex,
  );
  const startIndex = screen.indexOf(
    "const delivery = await startDelivery(payload);",
    payloadIndex,
  );

  assert.ok(payloadIndex >= 0 && preflightIndex > payloadIndex);
  assert.ok(startIndex > preflightIndex);
  assert.match(screen, /waterPreflightRunning/);
  assert.match(screen, /!scheduleForLater && waterBlocksImmediateMission/);
});
