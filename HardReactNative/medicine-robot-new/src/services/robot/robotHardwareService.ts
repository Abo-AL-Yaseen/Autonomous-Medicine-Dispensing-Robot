import {
    getApiErrorMessage,
    robotApi,
    unwrapAxiosData,
} from "@/src/config/api";
import { HealthResponse, RobotHardwareStatus } from "@/src/types";

export const getRobotHealth = async (): Promise<HealthResponse> => {
  try {
    const response = await robotApi.get<HealthResponse>("/health");
    return unwrapAxiosData(response);
  } catch (error) {
    throw new Error(
      getApiErrorMessage(error, "Unable to reach the robot health endpoint."),
    );
  }
};

export const getRobotPing = async (): Promise<HealthResponse> => {
  try {
    const response = await robotApi.get<HealthResponse>("/ping");
    return unwrapAxiosData(response);
  } catch (error) {
    throw new Error(
      getApiErrorMessage(error, "Unable to reach the robot ping endpoint."),
    );
  }
};

export const getRobotHardwareStatus =
  async (): Promise<RobotHardwareStatus> => {
    try {
      const response = await robotApi.get<RobotHardwareStatus>("/status");
      return unwrapAxiosData(response);
    } catch (error) {
      throw new Error(
        getApiErrorMessage(error, "Unable to load robot hardware status."),
      );
    }
  };
