import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  ROBOT_RTC_ENDPOINT,
  ROBOT_RTC_SYNC_ENDPOINT,
  robotClockErrorMessage,
} from "../src/services/robot/executorService.ts";
import {
  formatRobotClockTime,
  syncAndRefreshRobotClock,
} from "../src/services/robot/robotClockService.ts";

const rtc = {
  success: true,
  datetime: "2026-08-23T14:18:20",
  source: "DS1302",
  timezone: "Asia/Hebron",
};

test("mobile uses GET RTC data for the Robot Clock display", () => {
  assert.equal(ROBOT_RTC_ENDPOINT, "/rtc");
  assert.equal(formatRobotClockTime(rtc), "14:18:20");

  const screen = readFileSync(
    new URL("../src/screens/DispenserSetupScreen.tsx", import.meta.url),
    "utf8",
  );
  assert.match(screen, /Robot Clock/);
  assert.match(screen, /Timezone:/);
  assert.match(screen, /formatRobotClockTime/);
});

test("RTC sync posts explicitly and refreshes GET RTC afterward", async () => {
  const calls = [];
  const confirmed = await syncAndRefreshRobotClock({
    sync: async () => {
      calls.push("POST /rtc/sync-system");
      return { ...rtc, datetime: "2026-08-23T14:18:19" };
    },
    get: async () => {
      calls.push("GET /rtc");
      return rtc;
    },
  });

  assert.equal(ROBOT_RTC_SYNC_ENDPOINT, "/rtc/sync-system");
  assert.deepEqual(calls, ["POST /rtc/sync-system", "GET /rtc"]);
  assert.deepEqual(confirmed, rtc);
});

test("RTC hardware communication failures have a clear mobile message", () => {
  assert.equal(
    robotClockErrorMessage("HARDWARE_COMMUNICATION_FAILED", "fallback"),
    "Robot clock hardware communication failed. Check the Raspberry and ESP32 connection.",
  );
  assert.equal(
    robotClockErrorMessage("HARDWARE_UNAVAILABLE", "fallback"),
    "Robot clock hardware communication failed. Check the Raspberry and ESP32 connection.",
  );

  const screen = readFileSync(
    new URL("../src/screens/DispenserSetupScreen.tsx", import.meta.url),
    "utf8",
  );
  assert.match(screen, /Retry Robot Clock/);
  assert.match(screen, /clockSyncing/);
  assert.match(screen, /Robot clock synchronized successfully/);
});

test("robot API source has no hardcoded numeric IP address", () => {
  const config = readFileSync(
    new URL("../src/config/api.ts", import.meta.url),
    "utf8",
  );

  assert.match(config, /process\.env\.EXPO_PUBLIC_ROBOT_API_URL/);
  assert.doesNotMatch(config, /https?:\/\/(?:\d{1,3}\.){3}\d{1,3}/);
});
