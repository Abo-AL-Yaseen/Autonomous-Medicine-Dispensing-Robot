import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { robotApiBaseUrl } from "../src/config/api.ts";
import { waterLevelDisplay } from "../src/services/robot/waterLevelService.ts";

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
