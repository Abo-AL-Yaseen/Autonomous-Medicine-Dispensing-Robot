import assert from "node:assert/strict";
import test from "node:test";

import {
  createEmptyHeldDirections,
  LatestManualDriveDispatcher,
  resolveManualDriveState,
} from "../src/services/robot/manualDriveController.ts";

const successfulResponse = {
  success: true,
  response: "ACK|TEST",
};

const createDeferred = () => {
  let resolve;
  const promise = new Promise((promiseResolve) => {
    resolve = promiseResolve;
  });
  return { promise, resolve };
};

test("forward press and release resolve to forward then stop", () => {
  const held = createEmptyHeldDirections();
  held.forward = true;
  assert.equal(resolveManualDriveState(held), "MANUAL_FORWARD");

  held.forward = false;
  assert.equal(resolveManualDriveState(held), "MANUAL_STOP");
});

test("forward and right transitions return to the remaining held direction", () => {
  const held = createEmptyHeldDirections();
  held.forward = true;
  assert.equal(resolveManualDriveState(held), "MANUAL_FORWARD");

  held.right = true;
  assert.equal(resolveManualDriveState(held), "MANUAL_FORWARD_RIGHT");

  held.right = false;
  assert.equal(resolveManualDriveState(held), "MANUAL_FORWARD");

  held.forward = false;
  assert.equal(resolveManualDriveState(held), "MANUAL_STOP");
});

test("forward-left, backward-left, and backward-right resolve exactly", () => {
  assert.equal(
    resolveManualDriveState({
      forward: true,
      backward: false,
      left: true,
      right: false,
    }),
    "MANUAL_FORWARD_LEFT",
  );
  assert.equal(
    resolveManualDriveState({
      forward: false,
      backward: true,
      left: true,
      right: false,
    }),
    "MANUAL_BACKWARD_LEFT",
  );
  assert.equal(
    resolveManualDriveState({
      forward: false,
      backward: true,
      left: false,
      right: true,
    }),
    "MANUAL_BACKWARD_RIGHT",
  );
});

test("left and right alone pivot continuously", () => {
  assert.equal(
    resolveManualDriveState({
      forward: false,
      backward: false,
      left: true,
      right: false,
    }),
    "MANUAL_LEFT",
  );
  assert.equal(
    resolveManualDriveState({
      forward: false,
      backward: false,
      left: false,
      right: true,
    }),
    "MANUAL_RIGHT",
  );
});

test("contradictory axes resolve safely", () => {
  assert.equal(
    resolveManualDriveState({
      forward: true,
      backward: true,
      left: false,
      right: false,
    }),
    "MANUAL_STOP",
  );
  assert.equal(
    resolveManualDriveState({
      forward: true,
      backward: false,
      left: true,
      right: true,
    }),
    "MANUAL_FORWARD",
  );
  assert.equal(
    resolveManualDriveState({
      forward: false,
      backward: false,
      left: true,
      right: true,
    }),
    "MANUAL_STOP",
  );
});

test("latest desired state wins during quick press and release", async () => {
  const firstRequest = createDeferred();
  const calls = [];
  const dispatcher = new LatestManualDriveDispatcher({
    sendManual: (state) => {
      calls.push(state);
      return state === "MANUAL_FORWARD"
        ? firstRequest.promise
        : Promise.resolve(successfulResponse);
    },
    sendEmergencyStop: () => Promise.resolve(successfulResponse),
  });

  dispatcher.setDesired("MANUAL_FORWARD");
  dispatcher.setDesired("MANUAL_FORWARD_RIGHT");
  dispatcher.setDesired("MANUAL_FORWARD");
  dispatcher.setDesired("MANUAL_STOP");

  assert.deepEqual(calls, ["MANUAL_FORWARD"]);
  firstRequest.resolve(successfulResponse);
  await dispatcher.waitForIdle();

  assert.deepEqual(calls, ["MANUAL_FORWARD", "MANUAL_STOP"]);
});

test("emergency stop is dispatched before any newer queued manual state", async () => {
  const firstRequest = createDeferred();
  const calls = [];
  const successes = [];
  const dispatcher = new LatestManualDriveDispatcher({
    sendManual: (state) => {
      calls.push(`manual:${state}`);
      return firstRequest.promise;
    },
    sendEmergencyStop: () => {
      calls.push("emergency");
      return Promise.resolve(successfulResponse);
    },
    onSuccess: (state, emergency) => successes.push({ state, emergency }),
  });

  dispatcher.setDesired("MANUAL_FORWARD");
  dispatcher.emergencyStop();
  firstRequest.resolve(successfulResponse);
  await dispatcher.waitForIdle();

  assert.deepEqual(calls, ["manual:MANUAL_FORWARD", "emergency"]);
  assert.deepEqual(successes, [{ state: "MANUAL_STOP", emergency: true }]);
});
