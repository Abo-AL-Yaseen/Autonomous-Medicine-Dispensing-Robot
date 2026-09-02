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
  wait?: (milliseconds: number) => Promise<void>;
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

const READY_POLL_ATTEMPTS = 12;
const READY_POLL_INTERVAL_MS = 500;

export class ImmediateDeliveryStartError extends Error {
  constructor(
    message: string,
    readonly missionId: number | null = null,
    readonly retryable = false,
  ) {
    super(message);
    this.name = "ImmediateDeliveryStartError";
  }
}

const isExecutionStarting = (
  status: MissionExecutorStatus,
  missionId: number,
): boolean =>
  status.mission_id === missionId &&
  (status.state === "STARTING" || status.state === "GOING_TO_ROOM");

const asAlreadyStartedResponse = (
  status: MissionExecutorStatus,
): ExecutorStartResponse => ({
  success: true,
  result: status.state === "GOING_TO_ROOM" ? "STARTED" : "U_TURN_STARTED",
  message: null,
  executor: status,
});

const startError = (error: unknown, missionId: number): ImmediateDeliveryStartError => {
  const message = error instanceof Error ? error.message : String(error);
  if (message.includes("HOME_NOT_CONFIRMED")) {
    return new ImmediateDeliveryStartError(
      "Robot is not correctly positioned at HOME.",
      missionId,
      true,
    );
  }
  if (message.includes("WATER_EMPTY")) {
    return new ImmediateDeliveryStartError(
      "Water tank is empty. Fill it before starting delivery.",
      missionId,
      true,
    );
  }
  if (message.includes("WATER_LEVEL_SENSOR_ERROR")) {
    return new ImmediateDeliveryStartError(
      "Unable to verify the water level. Check the ultrasonic sensor.",
      missionId,
      true,
    );
  }
  return new ImmediateDeliveryStartError(message, missionId, false);
};

const ensureIntendedMission = (
  status: MissionExecutorStatus,
  missionId: number,
): void => {
  if (status.mission_id !== null && status.mission_id !== missionId) {
    throw new ImmediateDeliveryStartError(
      `MISSION_ID_MISMATCH: FastAPI loaded mission ${status.mission_id}, not newly created mission ${missionId}.`,
      missionId,
    );
  }
};

const startReadyMissionOnce = async (
  missionId: number,
  dependencies: Pick<ImmediateDeliveryDependencies, "getExecutorStatus" | "start" | "wait">,
  initialStatus: MissionExecutorStatus,
): Promise<ExecutorStartResponse> => {
  let status = initialStatus;
  const wait = dependencies.wait ??
    ((milliseconds: number) =>
      new Promise<void>((resolve) => setTimeout(resolve, milliseconds)));

  for (let attempt = 0; attempt < READY_POLL_ATTEMPTS; attempt += 1) {
    ensureIntendedMission(status, missionId);

    if (isExecutionStarting(status, missionId)) {
      return asAlreadyStartedResponse(status);
    }

    if (
      status.mission_id === missionId &&
      status.state === "READY_FOR_EXECUTION"
    ) {
      try {
        const started = await dependencies.start();
        ensureIntendedMission(started.executor, missionId);
        if (!started.success || !isExecutionStarting(started.executor, missionId)) {
          throw outcomeFailure(started.result, started.message);
        }
        return started;
      } catch (error) {
        throw startError(error, missionId);
      }
    }

    if (attempt < READY_POLL_ATTEMPTS - 1) {
      await wait(READY_POLL_INTERVAL_MS);
      status = await dependencies.getExecutorStatus();
    }
  }

  throw new ImmediateDeliveryStartError(
    `EXECUTOR_NOT_READY: Mission ${missionId} was not accepted for execution.`,
    missionId,
  );
};

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
  try {
    const claim = await dependencies.claim();
    if (claim.mission_id !== null && claim.mission_id !== missionId) {
      throw new ImmediateDeliveryStartError(
        `MISSION_ID_MISMATCH: FastAPI loaded mission ${claim.mission_id}, not newly created mission ${missionId}.`,
        missionId,
      );
    }

    const executor = await startReadyMissionOnce(
      missionId,
      dependencies,
      claim.executor,
    );
    return { mission, executor };
  } catch (error) {
    if (error instanceof ImmediateDeliveryStartError) throw error;
    throw startError(error, missionId);
  }
};

export const retryImmediateDeliveryStart = async (
  missionId: number,
  dependencies: Pick<
    ImmediateDeliveryDependencies,
    "getExecutorStatus" | "start" | "wait"
  > = defaultDependencies,
): Promise<ExecutorStartResponse> => {
  const status = await dependencies.getExecutorStatus();
  return startReadyMissionOnce(missionId, dependencies, status);
};

export const startImmediateDelivery = (
  payload: ImmediateDeliveryPayload,
): Promise<ImmediateDeliveryResult> =>
  runImmediateDeliveryFlow(payload, defaultDependencies);
