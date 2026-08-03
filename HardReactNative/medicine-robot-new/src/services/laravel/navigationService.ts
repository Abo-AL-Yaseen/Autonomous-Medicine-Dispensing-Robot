import {
    getApiErrorMessage,
    laravelApi,
    unwrapAxiosData,
} from "@/src/config/api";
import { NavigationDecision } from "@/src/types";

export const startRobotNavigation = async (
  missionId: number,
): Promise<{
  mission_id?: number;
  status?: string;
  [key: string]: unknown;
}> => {
  try {
    const response = await laravelApi.post<{
      mission_id?: number;
      status?: string;
      [key: string]: unknown;
    }>("/robot/navigation/start", { mission_id: missionId });
    return unwrapAxiosData(response);
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
): Promise<NavigationDecision> => {
  try {
    const response = await laravelApi.post<NavigationDecision>(
      "/robot/navigation/arrived",
      payload,
    );
    return unwrapAxiosData(response);
  } catch (error) {
    throw new Error(getApiErrorMessage(error, "Unable to confirm arrival."));
  }
};
