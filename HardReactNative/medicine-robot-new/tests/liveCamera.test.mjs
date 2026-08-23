import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  CAMERA_STATUS_ENDPOINT,
  CAMERA_STREAM_ENDPOINT,
  buildMjpegViewerHtml,
  buildRobotCameraUrl,
  isCameraReady,
  parseCameraStatus,
  shouldRenderCameraStream,
} from "../src/services/robot/cameraService.ts";

const readMobileSource = (relativePath) =>
  readFileSync(new URL(`../${relativePath}`, import.meta.url), "utf8");

test("camera URLs use the configured robot API base without a hardcoded host", () => {
  assert.equal(CAMERA_STATUS_ENDPOINT, "/camera/status");
  assert.equal(CAMERA_STREAM_ENDPOINT, "/camera/stream");
  assert.equal(
    buildRobotCameraUrl(CAMERA_STREAM_ENDPOINT, "http://robot.test:8000/"),
    "http://robot.test:8000/camera/stream",
  );

  const cameraSource = readMobileSource("src/services/robot/cameraService.ts");
  const configSource = readMobileSource("src/config/api.ts");
  assert.match(configSource, /process\.env\.EXPO_PUBLIC_ROBOT_API_URL/);
  assert.doesNotMatch(
    cameraSource,
    /localhost|127\.0\.0\.1|https?:\/\/(?:\d{1,3}\.){3}\d{1,3}/,
  );
});

test("camera status is validated before the MJPEG stream is eligible to render", () => {
  const ready = parseCameraStatus({
    camera_available: true,
    camera_open: true,
    error: null,
  });
  assert.equal(isCameraReady(ready), true);
  assert.equal(
    isCameraReady({ camera_available: false, camera_open: true }),
    false,
  );
  assert.throws(
    () => parseCameraStatus({ camera_available: true }),
    /Invalid camera status response/,
  );

  const component = readMobileSource("src/components/LiveCameraModal.tsx");
  assert.match(component, /getCameraStatus\(\)/);
  assert.match(component, /if \(!isCameraReady\(status\)\)/);
  assert.match(component, /Camera unavailable\./);
});

test("the MJPEG viewer loads the shared backend stream and reports load failures", () => {
  const html = buildMjpegViewerHtml("http://robot.test/camera/stream");
  assert.match(html, /http:\/\/robot\.test\/camera\/stream/);
  assert.match(html, /STREAM_READY/);
  assert.match(html, /STREAM_ERROR/);

  const component = readMobileSource("src/components/LiveCameraModal.tsx");
  assert.match(component, /Camera stream could not be loaded\./);
  assert.match(component, /Retry Live Camera/);
  assert.match(component, /setRetryKey\(\(current\) => current \+ 1\)/);
});

test("Manual Control and Delivery open the same reusable live camera view", () => {
  for (const screen of [
    "src/screens/ManualControlScreen.tsx",
    "src/screens/DeliveryScreen.tsx",
  ]) {
    const source = readMobileSource(screen);
    assert.match(source, /Open Live Camera/);
    assert.match(source, /<LiveCameraModal/);
    assert.match(source, /visible=\{cameraVisible\}/);
  }
});

test("closing or backgrounding the view prevents client stream rendering", () => {
  const base = {
    visible: true,
    appActive: true,
    cameraReady: true,
    streamFailed: false,
  };
  assert.equal(shouldRenderCameraStream(base), true);
  assert.equal(shouldRenderCameraStream({ ...base, visible: false }), false);
  assert.equal(shouldRenderCameraStream({ ...base, appActive: false }), false);
  assert.equal(shouldRenderCameraStream({ ...base, streamFailed: true }), false);

  const component = readMobileSource("src/components/LiveCameraModal.tsx");
  assert.match(component, /AppState\.addEventListener/);
  assert.match(component, /setViewState\("idle"\)/);
});

test("Delivery mission state and executor polling remain independent of camera viewing", () => {
  const delivery = readMobileSource("src/screens/DeliveryScreen.tsx");
  assert.match(delivery, /const pollExecutor = async \(\) =>/);
  assert.match(delivery, /getMissionExecutorStatus\(\)/);
  assert.match(delivery, /setTimeout\(pollExecutor, 1000\)/);
  assert.match(delivery, /setTimeout\(pollExecutor, 3000\)/);
  assert.match(delivery, /\}, \[missionState\]\);/);
});

test("backend camera endpoints still share the sole buffered ArUco camera service", () => {
  const api = readFileSync(
    new URL("../../../raspberry_controller/api.py", import.meta.url),
    "utf8",
  );
  const cameraService = readFileSync(
    new URL(
      "../../../raspberry_controller/services/camera/aruco_camera_service.py",
      import.meta.url,
    ),
    "utf8",
  );

  assert.match(api, /@application\.get\("\/camera\/status"\)/);
  assert.match(api, /@application\.get\("\/camera\/stream"\)/);
  assert.match(api, /camera_service\.get_preview_jpeg/);
  assert.match(api, /camera_service\.mjpeg_stream/);
  assert.doesNotMatch(api, /VideoCapture/);
  assert.equal((cameraService.match(/VideoCapture\(/g) ?? []).length, 1);
  assert.match(cameraService, /_latest_frame_copy/);
});
