import type {
  ApiSuccessResponse,
  HealthResponse,
  Medicine,
  MedicineDispensePayload,
  MedicineDispenseResponse,
  Mission,
  MissionExecutorState,
  MissionExecutorStatus,
  MovementResponse,
  ExecutorStartResponse,
  RobotHardwareStatus,
  RobotMode,
  RobotPingResponse,
  RobotRtcResponse,
  RobotStatus,
  Room,
  SchedulerTickResponse,
  WaterDispenseResponse,
} from "../types";

type UnknownRecord = Record<string, unknown>;

const isRecord = (value: unknown): value is UnknownRecord =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const invalidResponse = (context: string, detail: string): never => {
  throw new Error(`Invalid ${context} response: ${detail}`);
};

const requireRecord = (value: unknown, context: string): UnknownRecord =>
  isRecord(value) ? value : invalidResponse(context, "expected an object.");

const requireString = (
  value: unknown,
  context: string,
  field: string,
): string =>
  typeof value === "string"
    ? value
    : invalidResponse(context, `expected '${field}' to be a string.`);

const requireBoolean = (
  value: unknown,
  context: string,
  field: string,
): boolean =>
  typeof value === "boolean"
    ? value
    : invalidResponse(context, `expected '${field}' to be a boolean.`);

const requireInteger = (
  value: unknown,
  context: string,
  field: string,
  minimum = 1,
): number =>
  Number.isSafeInteger(value) && Number(value) >= minimum
    ? Number(value)
    : invalidResponse(
        context,
        `expected '${field}' to be an integer greater than or equal to ${minimum}.`,
      );

const optionalNullableString = (
  value: unknown,
  context: string,
  field: string,
): string | null | undefined => {
  if (value === undefined || value === null || typeof value === "string") {
    return value;
  }

  return invalidResponse(
    context,
    `expected '${field}' to be a string or null.`,
  );
};

const nullableMissionId = (
  value: unknown,
  context: string,
): number | null =>
  value === null
    ? null
    : requireInteger(value, context, "mission_id");

const missionExecutorStates: readonly MissionExecutorState[] = [
  "IDLE",
  "READY_FOR_EXECUTION",
  "STARTING",
  "GOING_TO_ROOM",
  "ARRIVED_AT_ROOM",
  "FAILED",
];

export const normalizeMissionExecutorStatus = (
  payload: unknown,
): MissionExecutorStatus => {
  const value = requireRecord(payload, "FastAPI executor status");
  const state = requireString(
    value.state,
    "FastAPI executor status",
    "state",
  );
  if (!missionExecutorStates.includes(state as MissionExecutorState)) {
    return invalidResponse(
      "FastAPI executor status",
      `unsupported executor state '${state}'.`,
    );
  }

  return {
    state: state as MissionExecutorState,
    mission_id: nullableMissionId(
      value.mission_id,
      "FastAPI executor status",
    ),
    last_error:
      optionalNullableString(
        value.last_error,
        "FastAPI executor status",
        "last_error",
      ) ?? null,
  };
};

export const normalizeRobotRtc = (payload: unknown): RobotRtcResponse => {
  const value = requireRecord(payload, "FastAPI RTC");
  const datetime = requireString(value.datetime, "FastAPI RTC", "datetime");
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/.test(datetime)) {
    return invalidResponse(
      "FastAPI RTC",
      "expected 'datetime' to be a timezone-naive ISO wall-clock.",
    );
  }

  return {
    success: requireBoolean(value.success, "FastAPI RTC", "success"),
    datetime,
    source: requireString(value.source, "FastAPI RTC", "source"),
    timezone: requireString(value.timezone, "FastAPI RTC", "timezone"),
  };
};

export const robotRtcToLaravelSchedule = (datetime: string): string => {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/.test(datetime)) {
    throw new Error("Robot RTC returned an invalid wall-clock value.");
  }

  return datetime.replace("T", " ");
};

export const normalizeSchedulerTick = (
  payload: unknown,
): SchedulerTickResponse => {
  const value = requireRecord(payload, "FastAPI scheduler tick");
  return {
    success: requireBoolean(value.success, "FastAPI scheduler tick", "success"),
    result: requireString(value.result, "FastAPI scheduler tick", "result"),
    mission_id: nullableMissionId(value.mission_id, "FastAPI scheduler tick"),
    message:
      optionalNullableString(
        value.message,
        "FastAPI scheduler tick",
        "message",
      ) ?? null,
    executor: normalizeMissionExecutorStatus(value.executor),
  };
};

export const normalizeExecutorStart = (
  payload: unknown,
): ExecutorStartResponse => {
  const value = requireRecord(payload, "FastAPI executor start");
  return {
    success: requireBoolean(value.success, "FastAPI executor start", "success"),
    result: requireString(value.result, "FastAPI executor start", "result"),
    message:
      optionalNullableString(
        value.message,
        "FastAPI executor start",
        "message",
      ) ?? null,
    executor: normalizeMissionExecutorStatus(value.executor),
  };
};

export const unwrapLaravelResource = (
  payload: unknown,
  context = "Laravel resource",
): unknown => {
  if (isRecord(payload) && Object.prototype.hasOwnProperty.call(payload, "data")) {
    if (payload.data === undefined) {
      return invalidResponse(context, "the 'data' field is undefined.");
    }
    return payload.data;
  }

  return payload;
};

export const normalizeLaravelCollection = <T>(
  payload: unknown,
  normalizeItem: (item: unknown) => T,
  context: string,
): T[] => {
  const value = unwrapLaravelResource(payload, context);
  if (!Array.isArray(value)) {
    return invalidResponse(context, "expected 'data' to contain an array.");
  }

  return value.map(normalizeItem);
};

export const normalizeRoom = (payload: unknown): Room => {
  const value = requireRecord(
    unwrapLaravelResource(payload, "room"),
    "room",
  );

  return {
    id: requireInteger(value.id, "room", "id"),
    number: requireString(value.room_number, "room", "room_number"),
    name: requireString(value.room_name, "room", "room_name"),
    description:
      optionalNullableString(value.description, "room", "description") ??
      null,
    created_at: optionalNullableString(value.created_at, "room", "created_at"),
    updated_at: optionalNullableString(value.updated_at, "room", "updated_at"),
  };
};

export const normalizeRooms = (payload: unknown): Room[] =>
  normalizeLaravelCollection(payload, normalizeRoom, "rooms");

export const normalizeMedicine = (payload: unknown): Medicine => {
  const value = requireRecord(
    unwrapLaravelResource(payload, "medicine"),
    "medicine",
  );
  const dispenserBox =
    value.dispenser_box === undefined || value.dispenser_box === null
      ? null
      : requireInteger(value.dispenser_box, "medicine", "dispenser_box");
  if (dispenserBox !== null && dispenserBox !== 1 && dispenserBox !== 2) {
    return invalidResponse(
      "medicine",
      "expected 'dispenser_box' to be 1, 2, or null.",
    );
  }

  return {
    id: requireInteger(value.id, "medicine", "id"),
    name: requireString(value.name, "medicine", "name"),
    description:
      optionalNullableString(value.description, "medicine", "description") ??
      null,
    stock: requireInteger(value.stock_quantity, "medicine", "stock_quantity", 0),
    dispenser_box: dispenserBox,
    created_at: optionalNullableString(
      value.created_at,
      "medicine",
      "created_at",
    ),
    updated_at: optionalNullableString(
      value.updated_at,
      "medicine",
      "updated_at",
    ),
  };
};

export const normalizeMedicines = (payload: unknown): Medicine[] =>
  normalizeLaravelCollection(payload, normalizeMedicine, "medicines");

const nestedResourceId = (
  value: unknown,
  context: string,
  field: string,
): number => {
  const nested = requireRecord(value, context);
  return requireInteger(nested.id, context, `${field}.id`);
};

export const normalizeMission = (payload: unknown): Mission => {
  const value = requireRecord(
    unwrapLaravelResource(payload, "mission"),
    "mission",
  );
  const roomId =
    value.room !== undefined
      ? nestedResourceId(value.room, "mission", "room")
      : requireInteger(value.room_id, "mission", "room_id");
  const medicineId =
    value.medicine !== undefined
      ? nestedResourceId(value.medicine, "mission", "medicine")
      : requireInteger(value.medicine_id, "mission", "medicine_id");
  const roomRecord = isRecord(value.room) ? value.room : null;
  const medicineRecord = isRecord(value.medicine) ? value.medicine : null;

  return {
    id: requireMissionId(value.id),
    room_id: roomId,
    medicine_id: medicineId,
    room:
      roomRecord?.room_name !== undefined ? normalizeRoom(roomRecord) : undefined,
    medicine:
      medicineRecord?.name !== undefined
        ? normalizeMedicine(medicineRecord)
        : undefined,
    quantity: requireInteger(value.quantity, "mission", "quantity"),
    status: requireString(value.status, "mission", "status"),
    scheduled_at:
      optionalNullableString(value.scheduled_at, "mission", "scheduled_at") ??
      null,
    created_at: optionalNullableString(
      value.created_at,
      "mission",
      "created_at",
    ),
    updated_at: optionalNullableString(
      value.updated_at,
      "mission",
      "updated_at",
    ),
  };
};

export const normalizeMissions = (payload: unknown): Mission[] =>
  normalizeLaravelCollection(payload, normalizeMission, "missions");

export const requireMissionId = (value: unknown): number => {
  if (!Number.isSafeInteger(value) || Number(value) <= 0) {
    throw new Error(
      "Mission creation response is missing a valid mission ID. Navigation was not started.",
    );
  }

  return Number(value);
};

const normalizeCurrentNode = (value: unknown): string | null => {
  if (value === null) return null;

  const node = requireRecord(value, "robot status");
  if (typeof node.node_code === "string") return node.node_code;

  return `Node ${requireInteger(node.id, "robot status", "current_node.id")}`;
};

const normalizeCurrentMissionId = (value: unknown): number | null =>
  value === null
    ? null
    : nestedResourceId(value, "robot status", "current_mission");

export const normalizeLaravelRobotStatus = (payload: unknown): RobotStatus => {
  const value = requireRecord(
    unwrapLaravelResource(payload, "robot status"),
    "robot status",
  );

  return {
    id:
      value.id === undefined
        ? undefined
        : requireInteger(value.id, "robot status", "id"),
    status: requireString(value.status, "robot status", "status"),
    battery:
      value.battery === null
        ? null
        : requireInteger(value.battery, "robot status", "battery", 0),
    connected: requireBoolean(value.connected, "robot status", "connected"),
    current_node: normalizeCurrentNode(value.current_node),
    current_mission_id: normalizeCurrentMissionId(value.current_mission),
    last_seen: optionalNullableString(
      value.last_seen,
      "robot status",
      "last_seen",
    ),
    created_at: optionalNullableString(
      value.created_at,
      "robot status",
      "created_at",
    ),
    updated_at: optionalNullableString(
      value.updated_at,
      "robot status",
      "updated_at",
    ),
  };
};

export const normalizeFastApiHealth = (payload: unknown): HealthResponse => {
  const value = requireRecord(payload, "FastAPI health");
  const hardwareConnected = requireBoolean(
    value.hardware_connected,
    "FastAPI health",
    "hardware_connected",
  );

  return {
    api_reachable: true,
    hardware_connected: hardwareConnected,
    connection: hardwareConnected ? "Connected" : "Disconnected",
    status: requireString(value.status, "FastAPI health", "status"),
  };
};

const normalizeStringRecord = (
  payload: unknown,
  context: string,
  field: string,
): Record<string, string> => {
  const value = requireRecord(payload, context);
  const entries = Object.entries(value);
  if (entries.some(([, item]) => typeof item !== "string")) {
    return invalidResponse(context, `expected every '${field}' value to be a string.`);
  }

  return Object.fromEntries(entries) as Record<string, string>;
};

const inferRobotMode = (statuses: Record<string, string>): RobotMode => {
  const combinedStatus = Object.values(statuses).join("|").toUpperCase();
  if (combinedStatus.includes("LINE")) return "Line Follow";
  if (combinedStatus.includes("MANUAL")) return "Manual";
  return "Autonomous";
};

export const disconnectedRobotHardwareStatus = (
  health: HealthResponse,
): RobotHardwareStatus => ({
  api_reachable: true,
  hardware_connected: false,
  connection: "Disconnected",
  status: "Hardware Disconnected",
  statuses: {},
  mode: "Unavailable",
  battery: null,
});

export const normalizeFastApiStatus = (
  payload: unknown,
  health: HealthResponse,
): RobotHardwareStatus => {
  const value = requireRecord(payload, "FastAPI status");
  const success = requireBoolean(value.success, "FastAPI status", "success");
  if (!success) return invalidResponse("FastAPI status", "'success' was false.");

  const statuses = normalizeStringRecord(
    value.statuses,
    "FastAPI status",
    "statuses",
  );

  return {
    api_reachable: true,
    hardware_connected: health.hardware_connected,
    connection: health.hardware_connected ? "Connected" : "Disconnected",
    status: statuses.ESP32 ?? health.status,
    statuses,
    mode: inferRobotMode(statuses),
    battery: null,
  };
};

export const failedRobotHardwareStatus = (
  error: string,
  apiReachable = false,
): RobotHardwareStatus => ({
  api_reachable: apiReachable,
  hardware_connected: false,
  connection: "Request Failed",
  status: "Request Failed",
  statuses: {},
  mode: "Unavailable",
  battery: null,
  error,
});

const requestErrorMessage = (error: unknown): string =>
  error instanceof Error && error.message
    ? error.message
    : "The robot API request failed.";

export const resolveRobotHardwareStatus = async (
  healthRequest: () => Promise<HealthResponse>,
  statusRequest: () => Promise<unknown>,
): Promise<RobotHardwareStatus> => {
  let health: HealthResponse;

  try {
    health = await healthRequest();
  } catch (error) {
    return failedRobotHardwareStatus(requestErrorMessage(error));
  }

  if (!health.hardware_connected) {
    return disconnectedRobotHardwareStatus(health);
  }

  try {
    return normalizeFastApiStatus(await statusRequest(), health);
  } catch (error) {
    return failedRobotHardwareStatus(requestErrorMessage(error), true);
  }
};

export const normalizeFastApiPing = (payload: unknown): RobotPingResponse => {
  const value = requireRecord(payload, "FastAPI ping");
  return {
    success: requireBoolean(value.success, "FastAPI ping", "success"),
    responses: normalizeStringRecord(
      value.responses,
      "FastAPI ping",
      "responses",
    ),
  };
};

export const normalizeFastApiCommand = (
  payload: unknown,
): MovementResponse => {
  const value = requireRecord(payload, "FastAPI command");
  return {
    success: requireBoolean(value.success, "FastAPI command", "success"),
    response: requireString(value.response, "FastAPI command", "response"),
    movement:
      value.movement === undefined
        ? undefined
        : requireString(value.movement, "FastAPI command", "movement"),
  };
};

export const buildMedicineDispensePayload = (
  dispenserBox: unknown,
  quantity: unknown,
): MedicineDispensePayload => {
  if (dispenserBox !== 1 && dispenserBox !== 2) {
    throw new Error("Medicine is not assigned to a valid dispenser box.");
  }
  if (!Number.isSafeInteger(quantity) || Number(quantity) < 1 || Number(quantity) > 10) {
    throw new Error("Medicine quantity must be between 1 and 10.");
  }

  return dispenserBox === 1
    ? { box1: Number(quantity), box2: 0 }
    : { box1: 0, box2: Number(quantity) };
};

export const normalizeFastApiDispense = (
  payload: unknown,
): MedicineDispenseResponse => {
  const value = requireRecord(payload, "FastAPI dispense");
  const requested = requireRecord(value.requested, "FastAPI dispense requested");
  const rawResults = requireRecord(value.results, "FastAPI dispense results");
  const results = Object.fromEntries(
    Object.entries(rawResults).map(([key, rawResult]) => {
      const result = requireRecord(rawResult, `FastAPI dispense ${key}`);
      return [
        key,
        {
          box_number: requireInteger(result.box_number, `FastAPI dispense ${key}`, "box_number"),
          requested_pills: requireInteger(result.requested_pills, `FastAPI dispense ${key}`, "requested_pills"),
          dispensed_pills: requireInteger(result.dispensed_pills, `FastAPI dispense ${key}`, "dispensed_pills"),
        },
      ];
    }),
  );

  return {
    success: requireBoolean(value.success, "FastAPI dispense", "success"),
    requested: {
      box1: requireInteger(requested.box1, "FastAPI dispense", "requested.box1", 0),
      box2: requireInteger(requested.box2, "FastAPI dispense", "requested.box2", 0),
    },
    results,
  };
};

export const normalizeFastApiWaterDispense = (
  payload: unknown,
): WaterDispenseResponse => {
  const value = requireRecord(payload, "FastAPI water dispense");
  const deliveryBasis = requireString(
    value.delivery_basis,
    "FastAPI water dispense",
    "delivery_basis",
  );
  if (deliveryBasis !== "calibrated_time") {
    return invalidResponse(
      "FastAPI water dispense",
      "expected 'delivery_basis' to be 'calibrated_time'.",
    );
  }

  const calibration = value.calibration_ml_per_second;
  if (typeof calibration !== "number" || !Number.isFinite(calibration) || calibration <= 0) {
    return invalidResponse(
      "FastAPI water dispense",
      "expected a positive 'calibration_ml_per_second'.",
    );
  }

  return {
    success: requireBoolean(value.success, "FastAPI water dispense", "success"),
    requested_amount_ml: requireInteger(
      value.requested_amount_ml,
      "FastAPI water dispense",
      "requested_amount_ml",
    ),
    delivery_basis: "calibrated_time",
    calibration_ml_per_second: calibration,
    duration_ms: requireInteger(value.duration_ms, "FastAPI water dispense", "duration_ms"),
  };
};

export const buildRobotScheduleDateTime = (
  date: string,
  time: string,
): string => {
  const dateMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  const timeMatch = /^(\d{2}):(\d{2})$/.exec(time);
  if (!dateMatch || !timeMatch) {
    throw new Error("Enter the scheduled date as YYYY-MM-DD and time as HH:MM.");
  }

  const [, yearText, monthText, dayText] = dateMatch;
  const [, hourText, minuteText] = timeMatch;
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const hour = Number(hourText);
  const minute = Number(minuteText);
  const validationDate = new Date(Date.UTC(year, month - 1, day, hour, minute));
  if (
    validationDate.getUTCFullYear() !== year ||
    validationDate.getUTCMonth() !== month - 1 ||
    validationDate.getUTCDate() !== day ||
    hour > 23 ||
    minute > 59
  ) {
    throw new Error("Enter a valid scheduled date and time.");
  }

  return `${date} ${time}:00`;
};

export const normalizeHardwareActionErrorMessage = (
  code: unknown,
  fallback: string,
): string => {
  switch (code) {
    case "HARDWARE_UNAVAILABLE":
      return "Hardware Disconnected.";
    case "WATER_FLOW_NOT_CALIBRATED":
      return "Water flow is not calibrated.";
    case "WATER_DURATION_OUT_OF_RANGE":
      return "The requested water amount exceeds the safe pump duration.";
    default:
      return fallback;
  }
};

export const normalizeSuccessResponse = (
  payload: unknown,
  context: string,
): ApiSuccessResponse => {
  const value = requireRecord(payload, context);
  return {
    success: requireBoolean(value.success, context, "success"),
  };
};

export const normalizeNavigationStartErrorMessage = (
  code: unknown,
  fallback: string,
): string => {
  switch (code) {
    case "HARDWARE_UNAVAILABLE":
      return "Robot hardware is disconnected.";
    case "ROBOT_API_UNAVAILABLE":
      return "Robot service is unavailable.";
    case "INVALID_ROBOT_API_RESPONSE":
      return "Robot service returned an invalid response.";
    default:
      return fallback;
  }
};

export const toLaravelRoomPayload = (payload: {
  name: string;
  number: string;
  description?: string | null;
}): UnknownRecord => ({
  room_name: payload.name,
  room_number: payload.number,
  description: payload.description ?? null,
});

export const toLaravelMedicinePayload = (payload: {
  name: string;
  description?: string | null;
  stock: number;
  dispenser_box: 1 | 2;
}): UnknownRecord => ({
  name: payload.name,
  description: payload.description ?? null,
  stock_quantity: payload.stock,
  dispenser_box: payload.dispenser_box,
});
