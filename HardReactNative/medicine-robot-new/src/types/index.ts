export type MissionState =
  | "Waiting"
  | "Moving"
  | "Delivering"
  | "Returning"
  | "Completed";

export type SelectorOption = string;
export type RobotConnection =
  | "Connected"
  | "Disconnected"
  | "Request Failed";
export type RobotMode =
  | "Autonomous"
  | "Manual"
  | "Line Follow"
  | "Unavailable";

export interface Room {
  id: number;
  number: string;
  name: string;
  description: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface Medicine {
  id: number;
  name: string;
  description: string | null;
  stock: number;
  dispenser_box: 1 | 2 | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface Mission {
  id: number;
  room_id: number;
  medicine_id: number;
  room?: Room;
  medicine?: Medicine;
  quantity: number;
  items: MissionItem[];
  status: string;
  scheduled_at: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface MissionItem {
  medicine_id: number;
  medicine?: Medicine;
  quantity: number;
}

export interface RobotStatus {
  id?: number;
  status: string;
  battery: number | null;
  connected: boolean;
  current_node: string | null;
  current_mission_id: number | null;
  last_seen?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface RobotHardwareStatus {
  api_reachable: boolean;
  hardware_connected: boolean;
  connection: RobotConnection;
  status: string;
  statuses: Record<string, string>;
  mode: RobotMode;
  battery: null;
  error?: string;
}

export interface DispenserDiskStatus {
  calibrated: boolean;
  slot: number;
}

export interface DispenserStatus {
  disk1: DispenserDiskStatus;
  disk2: DispenserDiskStatus;
}

export interface DispenserSetZeroResponse extends DispenserDiskStatus {
  box: 1 | 2;
}

export interface CreateMissionRequest {
  room_id: number;
  items?: { medicine_id: number; quantity: number }[];
  // Temporary legacy compatibility for existing callers during rollout.
  medicine_id?: number;
  quantity?: number;
  scheduled_at?: string | null;
}

export type MissionExecutorState =
  | "IDLE"
  | "READY_FOR_EXECUTION"
  | "STARTING"
  | "GOING_TO_ROOM"
  | "ARRIVED_AT_ROOM"
  | "WAITING_FOR_HAND"
  | "FAILED";

export interface MissionExecutorStatus {
  state: MissionExecutorState;
  mission_id: number | null;
  last_error: string | null;
}

export interface RobotRtcResponse {
  success: boolean;
  datetime: string;
  source: string;
  timezone: string;
}

export interface SchedulerTickResponse {
  success: boolean;
  result: string;
  mission_id: number | null;
  message: string | null;
  executor: MissionExecutorStatus;
}

export interface ExecutorStartResponse {
  success: boolean;
  result: string;
  message: string | null;
  executor: MissionExecutorStatus;
}

export interface NavigationDecision {
  decision?: string;
  action?: string;
  next_node?: string | null;
  mission_id?: number;
  [key: string]: unknown;
}

export interface ApiSuccessResponse {
  success: boolean;
}

export interface MovementResponse {
  success: boolean;
  response: string;
  movement?: string;
}

export interface MedicineDispensePayload {
  box1: number;
  box2: number;
}

export interface DispenseBoxResult {
  box_number: number;
  requested_pills: number;
  dispensed_pills: number;
}

export interface MedicineDispenseResponse {
  success: boolean;
  requested: MedicineDispensePayload;
  results: Record<string, DispenseBoxResult>;
}

export interface WaterDispenseResponse {
  success: boolean;
  requested_amount_ml: number;
  delivery_basis: "calibrated_time";
  calibration_ml_per_second: number;
  duration_ms: number;
}

export type WaterLevelStatus = "OK" | "LOW" | "EMPTY" | "SENSOR_ERROR";

export interface WaterLevelResponse {
  success: boolean;
  distance_cm: number | null;
  percent: number | null;
  status: WaterLevelStatus;
}

export interface LineStatus {
  success: boolean;
  status: string;
}

export interface LineSensorResponse {
  success: boolean;
  reading: string;
}

export interface HealthResponse {
  api_reachable: true;
  hardware_connected: boolean;
  connection: Exclude<RobotConnection, "Request Failed">;
  status: string;
}

export interface RobotPingResponse {
  success: boolean;
  responses: Record<string, string>;
}

export interface CreateRoomRequest {
  name: string;
  number: string;
  description?: string | null;
}

export interface CreateMedicineRequest {
  name: string;
  description?: string | null;
  stock: number;
  dispenser_box: 1 | 2;
}

export interface RobotStatusData {
  status: string;
  battery: number;
  location: string;
}

export interface StatusCardProps {
  label: string;
  value: string;
  accent?: boolean;
}
