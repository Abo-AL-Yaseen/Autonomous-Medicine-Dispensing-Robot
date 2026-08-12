import {
  getApiErrorMessage,
  robotApi,
  unwrapAxiosData,
} from "@/src/config/api";
import {
  normalizeExecutorStart,
  normalizeMissionExecutorStatus,
  normalizeRobotRtc,
  normalizeSchedulerTick,
} from "@/src/services/apiAdapters";
import {
  ExecutorStartResponse,
  MissionExecutorStatus,
  RobotRtcResponse,
  SchedulerTickResponse,
} from "@/src/types";

const outcomeErrorMessage = (error: unknown, fallback: string): string => {
  const message = getApiErrorMessage(error, fallback);
  if (
    typeof error === "object" &&
    error !== null &&
    "response" in error &&
    typeof error.response === "object" &&
    error.response !== null &&
    "data" in error.response &&
    typeof error.response.data === "object" &&
    error.response.data !== null &&
    "result" in error.response.data &&
    typeof error.response.data.result === "string"
  ) {
    return `${error.response.data.result}: ${message}`;
  }

  return message;
};

export const getMissionExecutorStatus =
  async (): Promise<MissionExecutorStatus> => {
    try {
      const response = await robotApi.get<unknown>("/executor/status");
      return normalizeMissionExecutorStatus(unwrapAxiosData(response));
    } catch (error) {
      throw new Error(
        getApiErrorMessage(error, "Unable to load the mission executor status."),
      );
    }
  };

export const getRobotRtc = async (): Promise<RobotRtcResponse> => {
  try {
    const response = await robotApi.get<unknown>("/rtc");
    return normalizeRobotRtc(unwrapAxiosData(response));
  } catch (error) {
    throw new Error(getApiErrorMessage(error, "Unable to read the robot RTC."));
  }
};

export const claimDueMission = async (): Promise<SchedulerTickResponse> => {
  try {
    const response = await robotApi.post<unknown>("/scheduler/tick");
    return normalizeSchedulerTick(unwrapAxiosData(response));
  } catch (error) {
    throw new Error(
      outcomeErrorMessage(error, "Unable to load the mission into the executor."),
    );
  }
};

export const startMissionExecutor =
  async (): Promise<ExecutorStartResponse> => {
    try {
      const response = await robotApi.post<unknown>("/executor/start");
      return normalizeExecutorStart(unwrapAxiosData(response));
    } catch (error) {
      throw new Error(
        outcomeErrorMessage(error, "Unable to start mission execution."),
      );
    }
  };
