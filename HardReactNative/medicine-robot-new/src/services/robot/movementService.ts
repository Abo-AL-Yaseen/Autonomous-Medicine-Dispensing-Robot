import {
    getApiErrorMessage,
    robotApi,
    unwrapAxiosData,
} from "@/src/config/api";
import { MovementResponse } from "@/src/types";

const movementRequest = async (endpoint: string): Promise<MovementResponse> => {
  try {
    const response = await robotApi.post<MovementResponse>(endpoint);
    return unwrapAxiosData(response);
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
