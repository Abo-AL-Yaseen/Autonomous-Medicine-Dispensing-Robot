export type MissionState =
  | "Waiting"
  | "Moving"
  | "Delivering"
  | "Returning"
  | "Completed";

export type SelectorOption = string;
export type RobotConnection = "Connected" | "Disconnected";
export type RobotMode = "Autonomous" | "Manual" | "Line Follow";

export interface Room {
  id: number;
  name: string;
  description?: string;
  [key: string]: unknown;
}

export interface Medicine {
  id: number;
  name: string;
  dosage?: string;
  stock?: number;
  [key: string]: unknown;
}

export interface Mission {
  id?: number;
  room_id: number;
  medicine_id: number;
  quantity: number;
  status?: string;
  created_at?: string;
  updated_at?: string;
  [key: string]: unknown;
}

export interface RobotStatus {
  id?: number;
  status?: string;
  battery?: number | null;
  connected?: boolean;
  current_node?: string | null;
  current_mission?: string | null;
  mode?: string;
  is_moving?: boolean;
  line_following?: boolean;
  updated_at?: string;
  [key: string]: unknown;
}

export interface RobotHardwareStatus extends RobotStatus {
  voltage?: number | null;
  temperature?: number | null;
  last_seen?: string;
}

export interface CreateMissionRequest {
  room_id: number;
  medicine_id: number;
  quantity: number;
}

export interface NavigationDecision {
  decision?: string;
  action?: string;
  next_node?: string | null;
  mission_id?: number;
  [key: string]: unknown;
}

export interface MovementResponse {
  ok: boolean;
  action: string;
  message?: string;
  [key: string]: unknown;
}

export interface LineStatus {
  active?: boolean;
  status?: string;
  sensors?: number[];
  [key: string]: unknown;
}

export interface LineSensorResponse {
  sensors: number[];
  status?: string;
  [key: string]: unknown;
}

export interface HealthResponse {
  ok?: boolean;
  status?: string;
  timestamp?: string;
  [key: string]: unknown;
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
