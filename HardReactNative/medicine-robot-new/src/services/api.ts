import { getMedicines } from "@/src/services/laravel/medicineService";
import { startImmediateDelivery } from "@/src/services/deliveryService";
import { startRobotNavigation as startLaravelNavigation } from "@/src/services/laravel/navigationService";
import { getLaravelRobotStatus } from "@/src/services/laravel/robotStatusService";
import { getRooms } from "@/src/services/laravel/roomService";
import {
    startLineFollowing,
    stopLineFollowing,
} from "@/src/services/robot/lineService";
import {
    manualDriveBackward,
    manualDriveBackwardLeft,
    manualDriveBackwardRight,
    manualDriveForward,
    manualDriveForwardLeft,
    manualDriveForwardRight,
    manualDriveLeft,
    manualDriveRight,
    manualDriveStop,
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
  items: { medicine_id: number; quantity: number }[];
}) => startImmediateDelivery(payload);

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
export const manualForward = () => manualDriveForward();
export const manualBackward = () => manualDriveBackward();
export const manualLeft = () => manualDriveLeft();
export const manualRight = () => manualDriveRight();
export const manualForwardLeft = () => manualDriveForwardLeft();
export const manualForwardRight = () => manualDriveForwardRight();
export const manualBackwardLeft = () => manualDriveBackwardLeft();
export const manualBackwardRight = () => manualDriveBackwardRight();
export const manualStop = () => manualDriveStop();
export const dispenseSelectedMedicine = dispenseMedicine;
export const dispenseSelectedWater = dispenseWater;

export {
  intersectionLeft,
  intersectionRight,
  intersectionStraight,
  uTurn,
} from "@/src/services/robot/lineService";
export { startLaravelNavigation as startRobotNavigation };

