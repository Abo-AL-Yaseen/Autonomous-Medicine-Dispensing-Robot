import {
  getApiErrorCode,
  getApiErrorMessage,
  robotApi,
  unwrapAxiosData,
} from "@/src/config/api";
import {
  normalizeExecutorStart,
  normalizeManualRecoveryResponse,
  normalizeMissionExecutorStatus,
  normalizeRobotRtc,
  normalizeSchedulerTick,
} from "@/src/services/apiAdapters";
import {
  ExecutorStartResponse,
  MissionExecutorStatus,
  RobotRtcResponse,
  SchedulerTickResponse,
  ManualRecoveryResponse,
} from "@/src/types";

export const ROBOT_RTC_ENDPOINT = "/rtc";
export const ROBOT_RTC_SYNC_ENDPOINT = "/rtc/sync-system";
export const MANUAL_RECOVERY_RESUME_ENDPOINT = "/executor/manual-recovery/resume";
export const MANUAL_RECOVERY_CANCEL_ENDPOINT = "/executor/manual-recovery/cancel";

export const robotClockErrorMessage = (
  code: string | null,
  fallback: string,
): string =>
  code === "HARDWARE_UNAVAILABLE" ||
  code === "HARDWARE_COMMUNICATION_FAILED"
    ? "Robot clock hardware communication failed. Check the Raspberry and ESP32 connection."
    : fallback;

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

const manualRecoveryRequest = async (
  endpoint: string,
): Promise<ManualRecoveryResponse> => {
  try {
    const response = await robotApi.post<unknown>(endpoint);
    return normalizeManualRecoveryResponse(unwrapAxiosData(response));
  } catch (error) {
    throw new Error(
      getApiErrorMessage(error, "Unable to update manual route recovery."),
    );
  }
};

export const resumeManualRecovery = () =>
  manualRecoveryRequest(MANUAL_RECOVERY_RESUME_ENDPOINT);

export const cancelManualRecovery = () =>
  manualRecoveryRequest(MANUAL_RECOVERY_CANCEL_ENDPOINT);

export const getRobotRtc = async (): Promise<RobotRtcResponse> => {
  try {
    const response = await robotApi.get<unknown>(ROBOT_RTC_ENDPOINT);
    return normalizeRobotRtc(unwrapAxiosData(response));
  } catch (error) {
    throw new Error(
      robotClockErrorMessage(
        getApiErrorCode(error),
        getApiErrorMessage(error, "Unable to read the robot RTC."),
      ),
    );
  }
};

export const syncRobotRtc = async (): Promise<RobotRtcResponse> => {
  try {
    const response = await robotApi.post<unknown>(ROBOT_RTC_SYNC_ENDPOINT);
    return normalizeRobotRtc(unwrapAxiosData(response));
  } catch (error) {
    const code = getApiErrorCode(error);
    throw new Error(
      robotClockErrorMessage(
        code,
        getApiErrorMessage(error, "Unable to synchronize the robot RTC."),
      ),
    );
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
