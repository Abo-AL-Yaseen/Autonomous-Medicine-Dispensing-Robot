import { useEffect, useState } from "react";

import { getLaravelRobotStatus } from "@/src/services/laravel/robotStatusService";
import { getRobotHardwareStatus } from "@/src/services/robot/robotHardwareService";
import type { RobotConnection, RobotMode } from "@/src/types";

const errorMessage = (error: unknown, fallback: string): string =>
  error instanceof Error && error.message ? error.message : fallback;

export const useRobotStatus = () => {
  const [status, setStatus] = useState("Ready");
  const [battery, setBattery] = useState(0);
  const [connection, setConnection] =
    useState<RobotConnection>("Disconnected");
  const [mode, setMode] = useState<RobotMode>("Autonomous");
  const [location, setLocation] = useState("Waiting");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadStatus = async () => {
      setLoading(true);

      const [laravelResult, hardwareResult] = await Promise.allSettled([
        getLaravelRobotStatus(),
        getRobotHardwareStatus(),
      ]);
      const errors: string[] = [];

      if (laravelResult.status === "fulfilled") {
        const laravelStatus = laravelResult.value;
        setStatus(laravelStatus.status);
        setBattery(laravelStatus.battery ?? 0);
        setLocation(laravelStatus.current_node ?? "Waiting");
      } else {
        errors.push(
          errorMessage(
            laravelResult.reason,
            "Unable to load the Laravel robot status.",
          ),
        );
      }

      if (hardwareResult.status === "fulfilled") {
        const hardwareStatus = hardwareResult.value;
        setConnection(hardwareStatus.connection);
        setMode(hardwareStatus.mode);

        if (laravelResult.status === "rejected") {
          setStatus(hardwareStatus.status);
        }

        if (hardwareStatus.error) errors.push(hardwareStatus.error);
      } else {
        setConnection("Request Failed");
        setMode("Unavailable");
        errors.push(
          errorMessage(
            hardwareResult.reason,
            "Unable to load the FastAPI hardware status.",
          ),
        );
      }

      setError(errors.length > 0 ? errors.join(" ") : null);
      setLoading(false);
    };

    void loadStatus();
  }, []);

  return { status, battery, connection, mode, location, loading, error };
};
