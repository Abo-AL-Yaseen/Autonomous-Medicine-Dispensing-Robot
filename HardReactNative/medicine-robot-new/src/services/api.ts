import { getMedicines } from "@/src/services/laravel/medicineService";
import { createMission } from "@/src/services/laravel/missionService";
import { startRobotNavigation as startLaravelNavigation } from "@/src/services/laravel/navigationService";
import { getLaravelRobotStatus } from "@/src/services/laravel/robotStatusService";
import { getRooms } from "@/src/services/laravel/roomService";
import { requireMissionId } from "@/src/services/apiAdapters";
import {
    startLineFollowing,
    stopLineFollowing,
} from "@/src/services/robot/lineService";
import {
    moveRobotBackward,
    moveRobotForward,
    moveRobotLeft,
    moveRobotRight,
    stopRobotMovement,
} from "@/src/services/robot/movementService";
import { getRobotHardwareStatus } from "@/src/services/robot/robotHardwareService";
import { dispenseMedicine } from "@/src/services/robot/dispenseService";
import { dispenseWater } from "@/src/services/robot/waterService";

export const startDelivery = async (payload: {
  room_id: number;
  medicine_id: number;
  quantity: number;
}) => {
  const mission = await createMission(payload);
  const missionId = requireMissionId(mission.id);
  const startResult = await startLaravelNavigation(missionId);
  return {
    ok: true,
    status: mission.status ?? "delivery started",
    mission,
    startResult,
  };
};

export const loadRooms = () => getRooms();
export const loadMedicines = () => getMedicines();
export const loadRobotStatus = () => getLaravelRobotStatus();
export const loadHardwareStatus = () => getRobotHardwareStatus();

export const moveForward = () => moveRobotForward();
export const moveBackward = () => moveRobotBackward();
export const turnLeft = () => moveRobotLeft();
export const turnRight = () => moveRobotRight();
export const stopRobot = () => stopRobotMovement();
export const startLineFollow = () => startLineFollowing();
export const stopLineFollow = () => stopLineFollowing();
export const emergencyStop = () => stopRobotMovement();
export const dispenseSelectedMedicine = dispenseMedicine;
export const dispenseSelectedWater = dispenseWater;

export { startLaravelNavigation as startRobotNavigation };

