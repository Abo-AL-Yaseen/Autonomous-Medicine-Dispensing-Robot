import {
    getApiErrorMessage,
    robotApi,
    unwrapAxiosData,
} from "@/src/config/api";
import { normalizeFastApiCommand } from "@/src/services/apiAdapters";
import { LineSensorResponse, LineStatus, MovementResponse } from "@/src/types";

export const getLineStatus = async (): Promise<LineStatus> => {
  try {
    const response = await robotApi.get<LineStatus>("/line/status");
    return unwrapAxiosData(response);
  } catch (error) {
    throw new Error(getApiErrorMessage(error, "Unable to load line status."));
  }
};

export const getLineSensors = async (): Promise<LineSensorResponse> => {
  try {
    const response = await robotApi.get<LineSensorResponse>("/line/sensors");
    return unwrapAxiosData(response);
  } catch (error) {
    throw new Error(getApiErrorMessage(error, "Unable to load line sensors."));
  }
};

export const startLineFollowing = async (): Promise<MovementResponse> => {
  try {
    const response = await robotApi.post<unknown>("/line/start");
    return normalizeFastApiCommand(unwrapAxiosData(response));
  } catch (error) {
    throw new Error(
      getApiErrorMessage(error, "Unable to start line following."),
    );
  }
};

export const stopLineFollowing = async (): Promise<MovementResponse> => {
  try {
    const response = await robotApi.post<unknown>("/line/stop");
    return normalizeFastApiCommand(unwrapAxiosData(response));
  } catch (error) {
    throw new Error(
      getApiErrorMessage(error, "Unable to stop line following."),
    );
  }
};
