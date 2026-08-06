import {
    getApiErrorMessage,
    robotApi,
    unwrapAxiosData,
} from "@/src/config/api";
import {
  normalizeFastApiHealth,
  normalizeFastApiPing,
  resolveRobotHardwareStatus,
} from "@/src/services/apiAdapters";
import {
  HealthResponse,
  RobotHardwareStatus,
  RobotPingResponse,
} from "@/src/types";

export const getRobotHealth = async (): Promise<HealthResponse> => {
  try {
    const response = await robotApi.get<unknown>("/health");
    return normalizeFastApiHealth(unwrapAxiosData(response));
  } catch (error) {
    throw new Error(
      getApiErrorMessage(error, "Unable to reach the robot health endpoint."),
    );
  }
};

export const getRobotPing = async (): Promise<RobotPingResponse> => {
  try {
    const response = await robotApi.get<unknown>("/ping");
    return normalizeFastApiPing(unwrapAxiosData(response));
  } catch (error) {
    throw new Error(
      getApiErrorMessage(error, "Unable to reach the robot ping endpoint."),
    );
  }
};

export const getRobotHardwareStatus =
  async (): Promise<RobotHardwareStatus> => {
    return resolveRobotHardwareStatus(getRobotHealth, async () => {
      try {
        const response = await robotApi.get<unknown>("/status");
        return unwrapAxiosData(response);
      } catch (error) {
        throw new Error(
          getApiErrorMessage(error, "Unable to load robot hardware status."),
        );
      }
    });
  };
