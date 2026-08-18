import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  normalizeDispenserSetZero,
  normalizeDispenserStatus,
} from "../src/services/apiAdapters.ts";
import { requiredDispenserBoxes } from "../src/services/dispenserReadiness.ts";
import {
  DISPENSER_STATUS_ENDPOINT,
  dispenserSetZeroEndpoint,
} from "../src/services/robot/dispenserCalibrationService.ts";

const medicines = [
  { id: 21, name: "Dynamic one", dispenser_box: 1 },
  { id: 22, name: "Dynamic two", dispenser_box: 2 },
];

test("normalizes the authoritative FastAPI dispenser status", () => {
  assert.deepEqual(
    normalizeDispenserStatus({
      success: true,
      disk1: { calibrated: true, slot: 0 },
      disk2: { calibrated: false, slot: 7 },
    }),
    {
      disk1: { calibrated: true, slot: 0 },
      disk2: { calibrated: false, slot: 7 },
    },
  );
  assert.throws(
    () => normalizeDispenserStatus({ success: true, disk1: { calibrated: true, slot: 8 }, disk2: { calibrated: false, slot: 0 } }),
    /slot must be between 0 and 7/i,
  );
});

test("uses the existing set-zero endpoints for each box without movement", () => {
  assert.equal(DISPENSER_STATUS_ENDPOINT, "/dispenser/status");
  assert.equal(dispenserSetZeroEndpoint(1), "/dispenser/box/1/set-zero");
  assert.equal(dispenserSetZeroEndpoint(2), "/dispenser/box/2/set-zero");
  assert.deepEqual(
    normalizeDispenserSetZero({ success: true, box: 2, calibrated: true, slot: 0 }, 2),
    { box: 2, calibrated: true, slot: 0 },
  );
  const service = readFileSync(
    new URL("../src/services/robot/dispenserCalibrationService.ts", import.meta.url),
    "utf8",
  );
  assert.doesNotMatch(service, /movement|dispense\(/i);
});

test("derives only selected dispenser boxes from dynamic medicine data", () => {
  assert.deepEqual(requiredDispenserBoxes(medicines, [{ medicine_id: 21, quantity: 1 }]), [1]);
  assert.deepEqual(requiredDispenserBoxes(medicines, [{ medicine_id: 22, quantity: 1 }]), [2]);
  assert.deepEqual(
    requiredDispenserBoxes(medicines, [{ medicine_id: 21, quantity: 2 }, { medicine_id: 22, quantity: 1 }]),
    [1, 2],
  );
  assert.deepEqual(requiredDispenserBoxes(medicines, [{ medicine_id: 21, quantity: 0 }]), []);
});

test("setup and delivery screens refresh real status and expose calibration safety", () => {
  const setupScreen = readFileSync(
    new URL("../src/screens/DispenserSetupScreen.tsx", import.meta.url),
    "utf8",
  );
  const deliveryScreen = readFileSync(
    new URL("../src/screens/DeliveryScreen.tsx", import.meta.url),
    "utf8",
  );

  assert.match(setupScreen, /getDispenserStatus/);
  assert.match(setupScreen, /setDispenserSlotZero/);
  assert.match(setupScreen, /await refresh\(\)/);
  assert.match(setupScreen, /Robot dispenser service unavailable/);
  assert.match(deliveryScreen, /requiredDispenserBoxes/);
  assert.match(deliveryScreen, /must be calibrated before starting this mission/);
  assert.match(deliveryScreen, /Open Dispenser Setup/);
});
