import { robotTimezone } from "@/src/config/api";
import {
  requireMissionId,
  robotRtcToLaravelSchedule,
} from "@/src/services/apiAdapters";
import { createMission } from "@/src/services/laravel/missionService";
import {
  claimDueMission,
  getMissionExecutorStatus,
  getRobotRtc,
  startMissionExecutor,
} from "@/src/services/robot/executorService";
import {
  CreateMissionRequest,
  ExecutorStartResponse,
  Mission,
  MissionExecutorStatus,
  RobotRtcResponse,
  SchedulerTickResponse,
} from "@/src/types";

export interface ImmediateDeliveryPayload {
  room_id: number;
  items: { medicine_id: number; quantity: number }[];
}

export interface ImmediateDeliveryResult {
  mission: Mission;
  executor: ExecutorStartResponse;
}

export interface ImmediateDeliveryDependencies {
  getExecutorStatus: () => Promise<MissionExecutorStatus>;
  getRtc: () => Promise<RobotRtcResponse>;
  create: (payload: CreateMissionRequest) => Promise<Mission>;
  claim: () => Promise<SchedulerTickResponse>;
  start: () => Promise<ExecutorStartResponse>;
}

const defaultDependencies: ImmediateDeliveryDependencies = {
  getExecutorStatus: getMissionExecutorStatus,
  getRtc: getRobotRtc,
  create: createMission,
  claim: claimDueMission,
  start: startMissionExecutor,
};

const outcomeFailure = (
  result: string,
  message: string | null,
): Error => new Error(message ? `${result}: ${message}` : result);

export const runImmediateDeliveryFlow = async (
  payload: ImmediateDeliveryPayload,
  dependencies: ImmediateDeliveryDependencies,
): Promise<ImmediateDeliveryResult> => {
  const initialExecutor = await dependencies.getExecutorStatus();
  if (initialExecutor.state !== "IDLE") {
    const missionDetail = initialExecutor.mission_id
      ? ` (mission ${initialExecutor.mission_id})`
      : "";
    throw new Error(
      `EXECUTOR_BUSY: MissionExecutor is ${initialExecutor.state}${missionDetail}.`,
    );
  }

  const rtc = await dependencies.getRtc();
  if (!rtc.success) {
    throw new Error("INVALID_RTC: Robot RTC did not report success.");
  }
  if (rtc.timezone !== robotTimezone) {
    throw new Error(
      `ROBOT_TIMEZONE_MISMATCH: Robot reported ${rtc.timezone}; expected ${robotTimezone}.`,
    );
  }

  const mission = await dependencies.create({
    ...payload,
    scheduled_at: robotRtcToLaravelSchedule(rtc.datetime),
  });
  const missionId = requireMissionId(mission.id);

  const claim = await dependencies.claim();
  const claimLoadedMission = claim.result === "READY_FOR_EXECUTION";
  const backgroundSchedulerAlreadyLoadedMission =
    claim.result === "EXECUTOR_BUSY" &&
    claim.executor.state === "READY_FOR_EXECUTION";
  const missionIsReady =
    claim.success &&
    (claimLoadedMission || backgroundSchedulerAlreadyLoadedMission) &&
    claim.mission_id === missionId &&
    claim.executor.mission_id === missionId &&
    claim.executor.state === "READY_FOR_EXECUTION";
  if (!missionIsReady) {
    if (claim.mission_id !== null && claim.mission_id !== missionId) {
      throw new Error(
        `MISSION_ID_MISMATCH: FastAPI loaded mission ${claim.mission_id}, not newly created mission ${missionId}.`,
      );
    }
    throw outcomeFailure(claim.result, claim.message);
  }

  const executor = await dependencies.start();
  const missionStarted =
    executor.success === true &&
    executor.result === "STARTED" &&
    executor.executor.state === "GOING_TO_ROOM" &&
    executor.executor.mission_id === missionId;
  if (!missionStarted) {
    throw outcomeFailure(executor.result, executor.message);
  }

  return { mission, executor };
};

export const startImmediateDelivery = (
  payload: ImmediateDeliveryPayload,
): Promise<ImmediateDeliveryResult> =>
  runImmediateDeliveryFlow(payload, defaultDependencies);
