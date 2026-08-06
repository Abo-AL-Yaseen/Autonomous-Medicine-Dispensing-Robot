import {
    getApiErrorMessage,
    laravelApi,
    unwrapAxiosData,
} from "@/src/config/api";
import {
  normalizeSuccessResponse,
  requireMissionId,
} from "@/src/services/apiAdapters";
import { ApiSuccessResponse, NavigationDecision } from "@/src/types";

export const startRobotNavigation = async (
  missionId: number,
): Promise<ApiSuccessResponse> => {
  try {
    const validMissionId = requireMissionId(missionId);
    const response = await laravelApi.post<unknown>(
      "/robot/navigation/start",
      { mission_id: validMissionId },
    );
    return normalizeSuccessResponse(
      unwrapAxiosData(response),
      "navigation start",
    );
  } catch (error) {
    throw new Error(
      getApiErrorMessage(error, "Unable to start robot navigation."),
    );
  }
};

export const sendNavigationDecision = async (
  payload: NavigationDecision,
): Promise<NavigationDecision> => {
  try {
    const response = await laravelApi.post<NavigationDecision>(
      "/robot/navigation/decision",
      payload,
    );
    return unwrapAxiosData(response);
  } catch (error) {
    throw new Error(
      getApiErrorMessage(error, "Unable to send navigation decision."),
    );
  }
};

export const sendNavigationArrival = async (
  payload: NavigationDecision,
): Promise<ApiSuccessResponse> => {
  try {
    const response = await laravelApi.post<unknown>(
      "/robot/navigation/arrived",
      payload,
    );
    return normalizeSuccessResponse(
      unwrapAxiosData(response),
      "navigation arrival",
    );
  } catch (error) {
    throw new Error(getApiErrorMessage(error, "Unable to confirm arrival."));
  }
};
