import { useEffect, useState } from "react";

import { getLaravelRobotStatus } from "@/src/services/laravel/robotStatusService";
import { getRobotHardwareStatus } from "@/src/services/robot/robotHardwareService";

export const useRobotStatus = () => {
  const [status, setStatus] = useState("Ready");
  const [battery, setBattery] = useState(0);
  const [connection, setConnection] = useState("Disconnected");
  const [mode, setMode] = useState("Autonomous");
  const [location, setLocation] = useState("Waiting");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadStatus = async () => {
      try {
        setLoading(true);
        const [laravelStatus, hardwareStatus] = await Promise.all([
          getLaravelRobotStatus().catch(() => ({
            status: "Unavailable",
            battery: 0,
            current_node: null,
            current_mission: null,
            mode: "Autonomous",
          })),
          getRobotHardwareStatus().catch(() => ({
            status: "Disconnected",
            battery: 0,
            current_node: null,
            current_mission: null,
            mode: "Manual",
          })),
        ]);

        const laravelState =
          typeof laravelStatus.status === "string"
            ? laravelStatus.status
            : "Ready";
        const hardwareState =
          typeof hardwareStatus.status === "string"
            ? hardwareStatus.status
            : "Disconnected";

        setStatus(laravelState || hardwareState || "Ready");
        setBattery(
          Number(hardwareStatus.battery ?? laravelStatus.battery ?? 0),
        );
        setConnection(
          hardwareStatus &&
            (hardwareStatus as { connected?: boolean }).connected !== false
            ? "Connected"
            : "Disconnected",
        );
        const nextMode =
          typeof (laravelStatus as { mode?: string }).mode === "string"
            ? ((laravelStatus as { mode?: string }).mode ?? "Autonomous")
            : typeof (hardwareStatus as { mode?: string }).mode === "string"
              ? ((hardwareStatus as { mode?: string }).mode ?? "Autonomous")
              : "Autonomous";

        const nextLocationValue =
          typeof (laravelStatus as { current_node?: string | null })
            .current_node === "string" &&
          (laravelStatus as { current_node?: string | null }).current_node
            ? (laravelStatus as { current_node?: string | null }).current_node
            : typeof (hardwareStatus as { current_node?: string | null })
                  .current_node === "string" &&
                (hardwareStatus as { current_node?: string | null })
                  .current_node
              ? (hardwareStatus as { current_node?: string | null })
                  .current_node
              : "Waiting";

        const finalLocation = nextLocationValue ?? "Waiting";

        setMode(nextMode);
        setLocation(finalLocation);
        setError(null);
      } catch (loadError) {
        const message =
          loadError instanceof Error
            ? loadError.message
            : "Unable to load robot status.";
        setError(message);
      } finally {
        setLoading(false);
      }
    };

    loadStatus();
  }, []);

  return { status, battery, connection, mode, location, loading, error };
};
