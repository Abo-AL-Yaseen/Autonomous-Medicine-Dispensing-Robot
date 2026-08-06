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
  status: string;
  created_at?: string | null;
  updated_at?: string | null;
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

export interface ApiSuccessResponse {
  success: boolean;
}

export interface MovementResponse {
  success: boolean;
  response: string;
  movement?: string;
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
