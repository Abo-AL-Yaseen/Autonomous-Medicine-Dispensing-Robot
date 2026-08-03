import {
    getApiErrorMessage,
    laravelApi,
    unwrapAxiosData,
} from "@/src/config/api";
import { CreateMissionRequest, Mission } from "@/src/types";

export const getMissions = async (): Promise<Mission[]> => {
  try {
    const response = await laravelApi.get<Mission[]>("/missions");
    return unwrapAxiosData(response);
  } catch (error) {
    throw new Error(getApiErrorMessage(error, "Unable to load missions."));
  }
};

export const getMissionById = async (missionId: number): Promise<Mission> => {
  try {
    const response = await laravelApi.get<Mission>(`/missions/${missionId}`);
    return unwrapAxiosData(response);
  } catch (error) {
    throw new Error(
      getApiErrorMessage(error, `Unable to load mission ${missionId}.`),
    );
  }
};

export const createMission = async (
  payload: CreateMissionRequest,
): Promise<Mission> => {
  try {
    const response = await laravelApi.post<Mission>("/missions", payload);
    return unwrapAxiosData(response);
  } catch (error) {
    throw new Error(getApiErrorMessage(error, "Unable to create mission."));
  }
};

export const updateMission = async (
  missionId: number,
  payload: Partial<Mission>,
): Promise<Mission> => {
  try {
    const response = await laravelApi.patch<Mission>(
      `/missions/${missionId}`,
      payload,
    );
    return unwrapAxiosData(response);
  } catch (error) {
    throw new Error(
      getApiErrorMessage(error, `Unable to update mission ${missionId}.`),
    );
  }
};

export const deleteMission = async (missionId: number): Promise<void> => {
  try {
    await laravelApi.delete(`/missions/${missionId}`);
  } catch (error) {
    throw new Error(
      getApiErrorMessage(error, `Unable to delete mission ${missionId}.`),
    );
  }
};
