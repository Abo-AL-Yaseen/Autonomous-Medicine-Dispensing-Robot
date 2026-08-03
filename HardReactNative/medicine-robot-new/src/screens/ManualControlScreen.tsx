import React, { useEffect, useState } from "react";
import { Alert, ScrollView, StyleSheet, View } from "react-native";
import { Text } from "react-native-paper";

import RobotIcon from "@/src/assets/RobotIcon";
import { DirectionPad } from "@/src/components/DirectionPad";
import { PrimaryButton } from "@/src/components/PrimaryButton";
import { StatusCard } from "@/src/components/StatusCard";
import {
    emergencyStop,
    moveBackward,
    moveForward,
    startLineFollow,
    stopLineFollow,
    stopRobot,
    turnLeft,
    turnRight,
} from "@/src/services/api";
import { getRobotHardwareStatus } from "@/src/services/robot/robotHardwareService";
import { theme } from "@/src/theme/theme";

export default function ManualControlScreen() {
  const [status, setStatus] = useState("Ready");
  const [battery, setBattery] = useState(0);
  const [connection, setConnection] = useState("Disconnected");
  const [mode, setMode] = useState("Manual");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadHardwareState = async () => {
      try {
        setLoading(true);
        const data = await getRobotHardwareStatus();
        setStatus(typeof data.status === "string" ? data.status : "Ready");
        setBattery(Number(data.battery ?? 0));
        setConnection(data.connected === false ? "Disconnected" : "Connected");
        setMode(typeof data.mode === "string" ? data.mode : "Manual");
        setError(null);
      } catch (e) {
        const message =
          e instanceof Error
            ? e.message
            : "Unable to load robot hardware status.";
        setError(message);
        setConnection("Disconnected");
        setStatus("Unavailable");
      } finally {
        setLoading(false);
      }
    };

    loadHardwareState();
  }, []);

  const updateRobotState = async (
    action: () => Promise<{ ok: boolean; action: string; message?: string }>,
    nextStatus: string,
  ) => {
    try {
      setLoading(true);
      setError(null);
      await action();
      setStatus(nextStatus);
      const hardware = await getRobotHardwareStatus();
      setBattery(Number(hardware.battery ?? battery));
      setConnection(
        hardware.connected === false ? "Disconnected" : "Connected",
      );
    } catch (e) {
      const message =
        e instanceof Error ? e.message : "Movement command failed.";
      setError(message);
      Alert.alert("Robot Communication Error", message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <View style={styles.safeArea}>
      <ScrollView
        contentContainerStyle={styles.container}
        showsVerticalScrollIndicator={false}
      >
        <Text style={styles.title}>Manual Control</Text>

        <View style={styles.robotArea}>
          <RobotIcon />
        </View>

        <DirectionPad
          onForward={() =>
            updateRobotState(() => moveForward(), "Moving Forward")
          }
          onBackward={() =>
            updateRobotState(() => moveBackward(), "Moving Backward")
          }
          onLeft={() => updateRobotState(() => turnLeft(), "Turning Left")}
          onRight={() => updateRobotState(() => turnRight(), "Turning Right")}
          onStop={() => updateRobotState(() => stopRobot(), "Stopped")}
        />

        <View style={styles.primaryActions}>
          <PrimaryButton
            label="Start Line Follow"
            onPress={() =>
              updateRobotState(() => startLineFollow(), "Line Follow Active")
            }
            disabled={loading}
            loading={loading}
          />
          <PrimaryButton
            label="Stop Line Follow"
            onPress={() =>
              updateRobotState(() => stopLineFollow(), "Line Follow Off")
            }
            disabled={loading}
            loading={loading}
          />
          <PrimaryButton
            label="Emergency Stop"
            onPress={() =>
              updateRobotState(() => emergencyStop(), "Emergency Stop")
            }
            variant="danger"
            disabled={loading}
            loading={loading}
          />
        </View>

        {error ? <Text style={styles.errorText}>{error}</Text> : null}

        <View style={styles.statusGrid}>
          <StatusCard label="Robot Status" value={status} />
          <StatusCard label="Battery" value={`${battery}%`} />
          <StatusCard label="Connection" value={connection} />
          <StatusCard label="Mode" value={mode} />
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: theme.colors.background,
  },
  container: {
    paddingHorizontal: 20,
    paddingTop: 70,
    paddingBottom: 40,
  },
  title: {
    fontSize: 36,
    fontWeight: "700",
    color: theme.colors.textPrimary,
    letterSpacing: -0.8,
    marginBottom: 20,
  },
  robotArea: {
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 12,
  },
  primaryActions: {
    gap: 12,
    marginBottom: 24,
  },
  statusGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 12,
  },
  errorText: {
    marginBottom: 12,
    color: "#C62828",
    fontWeight: "600",
  },
});
