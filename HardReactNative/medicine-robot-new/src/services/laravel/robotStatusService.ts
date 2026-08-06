import {
    getApiErrorMessage,
    laravelApi,
    unwrapAxiosData,
} from "@/src/config/api";
import { normalizeLaravelRobotStatus } from "@/src/services/apiAdapters";
import { RobotStatus } from "@/src/types";

export const getLaravelRobotStatus = async (): Promise<RobotStatus> => {
  try {
    const response = await laravelApi.get<unknown>("/robot/status");
    return normalizeLaravelRobotStatus(unwrapAxiosData(response));
  } catch (error) {
    throw new Error(getApiErrorMessage(error, "Unable to load robot status."));
  }
};

export const updateLaravelRobotStatus = async (
  payload: Partial<
    Pick<RobotStatus, "battery" | "connected" | "status"> & {
      current_node_id: number | null;
      current_mission_id: number | null;
    }
  >,
): Promise<RobotStatus> => {
  try {
    const response = await laravelApi.patch<unknown>(
      "/robot/status",
      payload,
    );
    return normalizeLaravelRobotStatus(unwrapAxiosData(response));
  } catch (error) {
    throw new Error(
      getApiErrorMessage(error, "Unable to update robot status."),
    );
  }
};
