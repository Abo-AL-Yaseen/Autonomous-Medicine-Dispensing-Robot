import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { robotApiBaseUrl } from "../src/config/api.ts";
import { normalizeFastApiManualPump } from "../src/services/apiAdapters.ts";

test("manual pump adapter accepts the start, stop, and bounded run responses", () => {
  assert.deepEqual(
    normalizeFastApiManualPump({ success: true, pump: "ON" }),
    { success: true, pump: "ON" },
  );
  assert.deepEqual(
    normalizeFastApiManualPump({ success: true, pump: "OFF" }),
    { success: true, pump: "OFF" },
  );
  assert.deepEqual(
    normalizeFastApiManualPump({ success: true, pump: "OFF", ran_seconds: 5 }),
    { success: true, pump: "OFF", ran_seconds: 5 },
  );
  assert.throws(
    () => normalizeFastApiManualPump({ success: true, pump: "ON", ran_seconds: 31 }),
    /at most 30/,
  );
});

test("manual pump service uses the shared robot API without a hardcoded URL", () => {
  const service = readFileSync(
    new URL("../src/services/robot/manualPumpService.ts", import.meta.url),
    "utf8",
  );

  assert.match(service, /robotApi/);
  assert.match(service, /"\/water\/pump\/start"/);
  assert.match(service, /"\/water\/pump\/stop"/);
  assert.match(service, /"\/water\/pump\/run"/);
  assert.doesNotMatch(service, /https?:\/\//);
  assert.match(robotApiBaseUrl, /^https?:\/\//);
});

test("manual control exposes pump controls, blocks duplicate actions, and refreshes the level", () => {
  const screen = readFileSync(
    new URL("../src/screens/ManualControlScreen.tsx", import.meta.url),
    "utf8",
  );

  assert.match(screen, /label="Start Pump"/);
  assert.match(screen, /label="Stop Pump"/);
  assert.match(screen, /label="Run 5s"/);
  assert.match(screen, /label="Run 10s"/);
  assert.match(screen, /disabled=\{loading \|\| pumpLoading\}/);
  assert.match(screen, /pumpRequestInFlightRef\.current/);
  assert.match(screen, /await refreshWaterLevel\(\)/);
});
