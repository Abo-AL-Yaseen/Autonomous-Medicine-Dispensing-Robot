import {
    getApiErrorMessage,
    robotApi,
    unwrapAxiosData,
} from "@/src/config/api";
import { normalizeFastApiCommand } from "@/src/services/apiAdapters";
import { MovementResponse } from "@/src/types";

const movementRequest = async (endpoint: string): Promise<MovementResponse> => {
  try {
    const response = await robotApi.post<unknown>(endpoint);
    return normalizeFastApiCommand(unwrapAxiosData(response));
  } catch (error) {
    throw new Error(
      getApiErrorMessage(
        error,
        `Unable to send movement command to ${endpoint}.`,
      ),
    );
  }
};

export const moveRobotForward = () => movementRequest("/movement/forward");
export const moveRobotBackward = () => movementRequest("/movement/backward");
export const moveRobotLeft = () => movementRequest("/movement/left");
export const moveRobotRight = () => movementRequest("/movement/right");
export const stopRobotMovement = () => movementRequest("/movement/stop");

export const manualDriveForward = () =>
  movementRequest("/movement/manual/forward");
export const manualDriveBackward = () =>
  movementRequest("/movement/manual/backward");
export const manualDriveLeft = () => movementRequest("/movement/manual/left");
export const manualDriveRight = () => movementRequest("/movement/manual/right");
export const manualDriveForwardLeft = () =>
  movementRequest("/movement/manual/forward-left");
export const manualDriveForwardRight = () =>
  movementRequest("/movement/manual/forward-right");
export const manualDriveBackwardLeft = () =>
  movementRequest("/movement/manual/backward-left");
export const manualDriveBackwardRight = () =>
  movementRequest("/movement/manual/backward-right");
export const manualDriveStop = () => movementRequest("/movement/manual/stop");
