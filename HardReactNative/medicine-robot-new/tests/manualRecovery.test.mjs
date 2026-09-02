import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  MANUAL_RECOVERY_CANCEL_ENDPOINT,
  MANUAL_RECOVERY_RESUME_ENDPOINT,
} from "../src/services/robot/executorService.ts";

const deliveryScreen = readFileSync(
  new URL("../src/screens/DeliveryScreen.tsx", import.meta.url),
  "utf8",
);

test("manual recovery service uses the dedicated resume and cancel API", () => {
  assert.equal(
    MANUAL_RECOVERY_RESUME_ENDPOINT,
    "/executor/manual-recovery/resume",
  );
  assert.equal(
    MANUAL_RECOVERY_CANCEL_ENDPOINT,
    "/executor/manual-recovery/cancel",
  );
});

test("delivery UI shows Arabic guidance, countdown, controls, and guarded resume", () => {
  assert.match(
    deliveryScreen,
    /تم فقدان المسار\. أعد الروبوت إلى الخط ثم اضغط متابعة\./,
  );
  assert.match(deliveryScreen, /manual_recovery_seconds_remaining/);
  assert.match(deliveryScreen, /<DirectionPad/);
  assert.match(deliveryScreen, /label="متابعة المسار"/);
  assert.match(deliveryScreen, /label="إيقاف وإلغاء"/);
  assert.match(
    deliveryScreen,
    /manualRecoveryRequestRunning \|\|\s*executorStatus\.manual_recovery_can_resume/,
  );
  assert.match(deliveryScreen, /manualRecoveryError/);
});
