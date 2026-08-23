import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  ImmediateDeliveryStartError,
  retryImmediateDeliveryStart,
  runImmediateDeliveryFlow,
} from "../src/services/deliveryService.ts";

const idleExecutor = {
  state: "IDLE",
  mission_id: null,
  last_error: null,
};

const mission = {
  id: 42,
  room_id: 1,
  medicine_id: 2,
  quantity: 1,
  status: "pending",
  scheduled_at: "2026-08-12T09:30:00+00:00",
};

const buildDependencies = (overrides = {}) => {
  const calls = [];
  const dependencies = {
    getExecutorStatus: async () => {
      calls.push("executor-status");
      return idleExecutor;
    },
    getRtc: async () => {
      calls.push("rtc");
      return {
        success: true,
        datetime: "2026-08-12T12:30:00",
        source: "DS1302",
        timezone: "Asia/Hebron",
      };
    },
    create: async (payload) => {
      calls.push(["create", payload]);
      return mission;
    },
    claim: async () => {
      calls.push("claim");
      return {
        success: true,
        result: "READY_FOR_EXECUTION",
        mission_id: 42,
        message: null,
        executor: {
          state: "READY_FOR_EXECUTION",
          mission_id: 42,
          last_error: null,
        },
      };
    },
    start: async () => {
      calls.push("start");
      return {
        success: true,
        result: "STARTED",
        message: null,
        executor: {
          state: "GOING_TO_ROOM",
          mission_id: 42,
          last_error: null,
        },
      };
    },
    ...overrides,
  };

  return { calls, dependencies };
};

test("immediate delivery creates, claims, and starts the same mission", async () => {
  const { calls, dependencies } = buildDependencies();
  const result = await runImmediateDeliveryFlow(
    { room_id: 1, medicine_id: 2, quantity: 1 },
    dependencies,
  );

  assert.equal(result.mission.id, 42);
  assert.equal(result.executor.result, "STARTED");
  assert.deepEqual(calls, [
    "executor-status",
    "rtc",
    [
      "create",
      {
        room_id: 1,
        medicine_id: 2,
        quantity: 1,
        scheduled_at: "2026-08-12 12:30:00",
      },
    ],
    "claim",
    "start",
  ]);
});

test("immediate delivery accepts the existing U-turn-first executor startup", async () => {
  let startCalls = 0;
  const { dependencies } = buildDependencies({
    start: async () => {
      startCalls += 1;
      return {
        success: true,
        result: "U_TURN_STARTED",
        message: null,
        executor: {
          state: "STARTING",
          mission_id: 42,
          last_error: null,
        },
      };
    },
  });

  const result = await runImmediateDeliveryFlow(
    { room_id: 1, medicine_id: 2, quantity: 1 },
    dependencies,
  );

  assert.equal(result.executor.executor.state, "STARTING");
  assert.equal(startCalls, 1);
});

test("immediate delivery polls until only the newly created mission is ready", async () => {
  let executorStatusCalls = 0;
  let startCalls = 0;
  const { dependencies } = buildDependencies({
    getExecutorStatus: async () => {
      executorStatusCalls += 1;
      if (executorStatusCalls === 1) return idleExecutor;
      return {
        state: "READY_FOR_EXECUTION",
        mission_id: 42,
        last_error: null,
      };
    },
    claim: async () => ({
      success: true,
      result: "NO_DUE_MISSION",
      mission_id: null,
      message: null,
      executor: idleExecutor,
    }),
    start: async () => {
      startCalls += 1;
      return {
        success: true,
        result: "U_TURN_STARTED",
        message: null,
        executor: {
          state: "STARTING",
          mission_id: 42,
          last_error: null,
        },
      };
    },
    wait: async () => {},
  });

  await runImmediateDeliveryFlow(
    { room_id: 1, medicine_id: 2, quantity: 1 },
    dependencies,
  );

  assert.equal(executorStatusCalls, 2);
  assert.equal(startCalls, 1);
});

test("scheduler auto-start of the intended immediate mission is not started twice", async () => {
  let startCalls = 0;
  const { dependencies } = buildDependencies({
    claim: async () => ({
      success: true,
      result: "AUTO_EXECUTION_STARTED",
      mission_id: 42,
      message: null,
      executor: {
        state: "STARTING",
        mission_id: 42,
        last_error: null,
      },
    }),
    start: async () => {
      startCalls += 1;
      throw new Error("must not run");
    },
  });

  const result = await runImmediateDeliveryFlow(
    { room_id: 1, medicine_id: 2, quantity: 1 },
    dependencies,
  );

  assert.equal(result.executor.result, "U_TURN_STARTED");
  assert.equal(startCalls, 0);
});

test("immediate delivery preserves independently selected medicine items", async () => {
  const { calls, dependencies } = buildDependencies();
  const items = [
    { medicine_id: 2, quantity: 2 },
    { medicine_id: 7, quantity: 1 },
  ];

  await runImmediateDeliveryFlow({ room_id: 1, items }, dependencies);

  assert.deepEqual(calls[2], ["create", {
    room_id: 1,
    items,
    scheduled_at: "2026-08-12 12:30:00",
  }]);
});

test("delivery UI keeps dynamic medicines, visible quantities, and selected summary", () => {
  const screen = readFileSync(
    new URL("../src/screens/DeliveryScreen.tsx", import.meta.url),
    "utf8",
  );

  assert.match(screen, /medicines\.map\(\(medicine\)/);
  assert.match(screen, /selectedQuantities\[medicine\.id\] \?\? 0/);
  assert.match(screen, /fontSize: 34/);
  assert.match(screen, /Selected medicines/);
  assert.match(screen, /quantity > 0 \? "Selected" : "Not selected"/);
});

test("a busy executor prevents duplicate mission creation", async () => {
  let createCalls = 0;
  const { dependencies } = buildDependencies({
    getExecutorStatus: async () => ({
      state: "ARRIVED_AT_ROOM",
      mission_id: 7,
      last_error: null,
    }),
    create: async () => {
      createCalls += 1;
      return mission;
    },
  });

  await assert.rejects(
    runImmediateDeliveryFlow(
      { room_id: 1, medicine_id: 2, quantity: 1 },
      dependencies,
    ),
    /EXECUTOR_BUSY.*ARRIVED_AT_ROOM.*mission 7/i,
  );
  assert.equal(createCalls, 0);
});

test("Laravel creation failure prevents scheduler and executor calls", async () => {
  let claimCalls = 0;
  let startCalls = 0;
  const { dependencies } = buildDependencies({
    create: async () => {
      throw new Error("Laravel validation failed");
    },
    claim: async () => {
      claimCalls += 1;
      throw new Error("must not run");
    },
    start: async () => {
      startCalls += 1;
      throw new Error("must not run");
    },
  });

  await assert.rejects(
    runImmediateDeliveryFlow(
      { room_id: 1, medicine_id: 2, quantity: 1 },
      dependencies,
    ),
    /Laravel validation failed/,
  );
  assert.equal(claimCalls, 0);
  assert.equal(startCalls, 0);
});

test("a different claimed mission is never started", async () => {
  let startCalls = 0;
  const { dependencies } = buildDependencies({
    claim: async () => ({
      success: true,
      result: "READY_FOR_EXECUTION",
      mission_id: 41,
      message: null,
      executor: {
        state: "READY_FOR_EXECUTION",
        mission_id: 41,
        last_error: null,
      },
    }),
    start: async () => {
      startCalls += 1;
      throw new Error("must not run");
    },
  });

  await assert.rejects(
    runImmediateDeliveryFlow(
      { room_id: 1, medicine_id: 2, quantity: 1 },
      dependencies,
    ),
    /MISSION_ID_MISMATCH.*41.*42/i,
  );
  assert.equal(startCalls, 0);
});

test("a background scheduler claim of the same mission can be started", async () => {
  const { calls, dependencies } = buildDependencies({
    claim: async () => {
      calls.push("claim");
      return {
        success: true,
        result: "EXECUTOR_BUSY",
        mission_id: 42,
        message: "MissionExecutor is busy; no mission was claimed.",
        executor: {
          state: "READY_FOR_EXECUTION",
          mission_id: 42,
          last_error: null,
        },
      };
    },
  });

  const result = await runImmediateDeliveryFlow(
    { room_id: 1, medicine_id: 2, quantity: 1 },
    dependencies,
  );

  assert.equal(result.executor.result, "STARTED");
  assert.equal(calls.at(-1), "start");
});

test("executor failure is returned instead of reporting the mission moving", async () => {
  const { dependencies } = buildDependencies({
    start: async () => ({
      success: false,
      result: "LINE_FOLLOW_START_FAILED",
      message: "SERIAL_TIMEOUT: expected ACK",
      executor: {
        state: "FAILED",
        mission_id: 42,
        last_error: "SERIAL_TIMEOUT: expected ACK",
      },
    }),
  });

  await assert.rejects(
    runImmediateDeliveryFlow(
      { room_id: 1, medicine_id: 2, quantity: 1 },
      dependencies,
    ),
    /LINE_FOLLOW_START_FAILED: SERIAL_TIMEOUT: expected ACK/,
  );
});

test("HOME_NOT_CONFIRMED is clear and retryable without creating a mission", async () => {
  let startCalls = 0;
  const { dependencies } = buildDependencies({
    start: async () => {
      startCalls += 1;
      throw new Error("HOME_NOT_CONFIRMED: HOME_NOT_CONFIRMED");
    },
  });

  await assert.rejects(
    runImmediateDeliveryFlow(
      { room_id: 1, medicine_id: 2, quantity: 1 },
      dependencies,
    ),
    (error) => {
      assert.ok(error instanceof ImmediateDeliveryStartError);
      assert.equal(error.message, "Robot is not correctly positioned at HOME.");
      assert.equal(error.missionId, 42);
      assert.equal(error.retryable, true);
      return true;
    },
  );
  assert.equal(startCalls, 1);

  let retryStartCalls = 0;
  const retried = await retryImmediateDeliveryStart(42, {
    getExecutorStatus: async () => ({
      state: "READY_FOR_EXECUTION",
      mission_id: 42,
      last_error: "HOME_NOT_CONFIRMED",
    }),
    start: async () => {
      retryStartCalls += 1;
      return {
        success: true,
        result: "U_TURN_STARTED",
        message: null,
        executor: {
          state: "STARTING",
          mission_id: 42,
          last_error: null,
        },
      };
    },
  });

  assert.equal(retried.executor.state, "STARTING");
  assert.equal(retryStartCalls, 1);
});

test("scheduled delivery UI creates only the Laravel mission", () => {
  const screen = readFileSync(
    new URL("../src/screens/DeliveryScreen.tsx", import.meta.url),
    "utf8",
  );

  const scheduledBranch = screen.slice(
    screen.indexOf("if (scheduleForLater) {", screen.indexOf("const payload")),
    screen.indexOf("const delivery = await startDelivery(payload);"),
  );
  assert.match(scheduledBranch, /await createMission/);
  assert.doesNotMatch(scheduledBranch, /startDelivery|retryDeliveryStart/);
  assert.match(screen, /pendingImmediateMissionId/);
  assert.match(screen, /Retry Start/);
});
