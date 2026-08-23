import {
  getApiErrorCode,
  getApiErrorMessage,
  robotApi,
  robotApiBaseUrl,
  unwrapAxiosData,
} from "@/src/config/api";

export const CAMERA_STATUS_ENDPOINT = "/camera/status";
export const CAMERA_STREAM_ENDPOINT = "/camera/stream";

export interface CameraStatus {
  camera_available: boolean;
  camera_open: boolean;
  error?: string | null;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null;

export const buildRobotCameraUrl = (
  endpoint: string,
  baseUrl = robotApiBaseUrl,
): string => `${baseUrl.replace(/\/+$/, "")}/${endpoint.replace(/^\/+/, "")}`;

export const cameraStreamUrl = buildRobotCameraUrl(CAMERA_STREAM_ENDPOINT);

export const parseCameraStatus = (value: unknown): CameraStatus => {
  if (
    !isRecord(value) ||
    typeof value.camera_available !== "boolean" ||
    typeof value.camera_open !== "boolean"
  ) {
    throw new Error("Invalid camera status response from the robot.");
  }

  return {
    camera_available: value.camera_available,
    camera_open: value.camera_open,
    error: typeof value.error === "string" ? value.error : null,
  };
};

export const getCameraStatus = async (): Promise<CameraStatus> =>
  robotApi
    .get<unknown>(CAMERA_STATUS_ENDPOINT)
    .then(unwrapAxiosData)
    .then(parseCameraStatus);

export const isCameraReady = (status: CameraStatus): boolean =>
  status.camera_available && status.camera_open;

export const cameraStatusErrorMessage = (error: unknown): string => {
  const code = getApiErrorCode(error);
  if (
    code === "CAMERA_UNAVAILABLE" ||
    code === "CAMERA_INITIALIZATION_FAILED"
  ) {
    return "Camera unavailable.";
  }

  return getApiErrorMessage(
    error,
    "Unable to reach the robot camera. Check the robot connection and try again.",
  );
};

export const shouldRenderCameraStream = ({
  visible,
  appActive,
  cameraReady,
  streamFailed,
}: {
  visible: boolean;
  appActive: boolean;
  cameraReady: boolean;
  streamFailed: boolean;
}): boolean => visible && appActive && cameraReady && !streamFailed;

export const buildMjpegViewerHtml = (streamUrl: string): string => `
<!doctype html>
<html>
  <head>
    <meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no" />
    <style>
      html, body { margin: 0; width: 100%; height: 100%; background: #111827; overflow: hidden; }
      img { display: block; width: 100%; height: 100%; object-fit: contain; }
    </style>
  </head>
  <body>
    <img id="camera" alt="Robot live camera" />
    <script>
      const camera = document.getElementById("camera");
      camera.addEventListener("load", () => window.ReactNativeWebView.postMessage("STREAM_READY"), { once: true });
      camera.addEventListener("error", () => window.ReactNativeWebView.postMessage("STREAM_ERROR"), { once: true });
      camera.src = ${JSON.stringify(streamUrl)};
    </script>
  </body>
</html>`;
