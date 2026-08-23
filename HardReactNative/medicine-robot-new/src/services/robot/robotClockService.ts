import {
  getRobotRtc,
  syncRobotRtc,
} from "@/src/services/robot/executorService";
import { RobotRtcResponse } from "@/src/types";

export interface RobotClockDependencies {
  get: () => Promise<RobotRtcResponse>;
  sync: () => Promise<RobotRtcResponse>;
}

const defaultDependencies: RobotClockDependencies = {
  get: getRobotRtc,
  sync: syncRobotRtc,
};

export const formatRobotClockTime = (rtc: RobotRtcResponse): string =>
  rtc.datetime.slice(11, 19);

export const syncAndRefreshRobotClock = async (
  dependencies: RobotClockDependencies = defaultDependencies,
): Promise<RobotRtcResponse> => {
  await dependencies.sync();
  return dependencies.get();
};
