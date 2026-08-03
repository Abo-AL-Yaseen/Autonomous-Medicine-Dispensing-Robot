import {
    getApiErrorMessage,
    laravelApi,
    unwrapAxiosData,
} from "@/src/config/api";
import { RobotStatus } from "@/src/types";

export const getLaravelRobotStatus = async (): Promise<RobotStatus> => {
  try {
    const response = await laravelApi.get<RobotStatus>("/robot/status");
    return unwrapAxiosData(response);
  } catch (error) {
    throw new Error(getApiErrorMessage(error, "Unable to load robot status."));
  }
};

export const updateLaravelRobotStatus = async (
  payload: Partial<RobotStatus>,
): Promise<RobotStatus> => {
  try {
    const response = await laravelApi.patch<RobotStatus>(
      "/robot/status",
      payload,
    );
    return unwrapAxiosData(response);
  } catch (error) {
    throw new Error(
      getApiErrorMessage(error, "Unable to update robot status."),
    );
  }
};
