import React, { useEffect, useRef, useState } from "react";
import { Alert, ScrollView, StyleSheet, View } from "react-native";
import { Text } from "react-native-paper";

import RobotIcon from "@/src/assets/RobotIcon";
import { DirectionPad } from "@/src/components/DirectionPad";
import { MedicineSelector } from "@/src/components/MedicineSelector";
import { PrimaryButton } from "@/src/components/PrimaryButton";
import { QuantitySelector } from "@/src/components/QuantitySelector";
import { StatusCard } from "@/src/components/StatusCard";
import {
    emergencyStop,
    dispenseSelectedMedicine,
    dispenseSelectedWater,
    intersectionLeft,
    intersectionRight,
    intersectionStraight,
    manualBackward,
    manualBackwardLeft,
    manualBackwardRight,
    manualForward,
    manualForwardLeft,
    manualForwardRight,
    manualLeft,
    manualRight,
    manualStop,
    startLineFollow,
    stopLineFollow,
    uTurn,
} from "@/src/services/api";
import { getMedicines } from "@/src/services/laravel/medicineService";
import {
  LatestManualDriveDispatcher,
  ManualDriveState,
} from "@/src/services/robot/manualDriveController";
import { getRobotHardwareStatus } from "@/src/services/robot/robotHardwareService";
import {
  getWaterLevel,
  waterLevelDisplay,
} from "@/src/services/robot/waterLevelService";
import {
  runManualPump,
  startManualPump,
  stopManualPump,
} from "@/src/services/robot/manualPumpService";
import { theme } from "@/src/theme/theme";
import type {
  Medicine,
  MovementResponse,
  RobotConnection,
  RobotMode,
  WaterLevelResponse,
} from "@/src/types";

const manualDriveRequests: Record<
  ManualDriveState,
  () => Promise<MovementResponse>
> = {
  MANUAL_FORWARD: manualForward,
  MANUAL_BACKWARD: manualBackward,
  MANUAL_LEFT: manualLeft,
  MANUAL_RIGHT: manualRight,
  MANUAL_FORWARD_LEFT: manualForwardLeft,
  MANUAL_FORWARD_RIGHT: manualForwardRight,
  MANUAL_BACKWARD_LEFT: manualBackwardLeft,
  MANUAL_BACKWARD_RIGHT: manualBackwardRight,
  MANUAL_STOP: manualStop,
};

const manualDriveLabels: Record<ManualDriveState, string> = {
  MANUAL_FORWARD: "Moving Forward",
  MANUAL_BACKWARD: "Moving Backward",
  MANUAL_LEFT: "Manual Left",
  MANUAL_RIGHT: "Manual Right",
  MANUAL_FORWARD_LEFT: "Moving Forward Left",
  MANUAL_FORWARD_RIGHT: "Moving Forward Right",
  MANUAL_BACKWARD_LEFT: "Moving Backward Left",
  MANUAL_BACKWARD_RIGHT: "Moving Backward Right",
  MANUAL_STOP: "Stopped",
};

export default function ManualControlScreen() {
  const [status, setStatus] = useState("Ready");
  const [battery, setBattery] = useState<number | null>(null);
  const [connection, setConnection] =
    useState<RobotConnection>("Disconnected");
  const [mode, setMode] = useState<RobotMode>("Manual");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [medicines, setMedicines] = useState<Medicine[]>([]);
  const [selectedMedicine, setSelectedMedicine] = useState("0");
  const [medicineQuantity, setMedicineQuantity] = useState(1);
  const [waterAmountMl, setWaterAmountMl] = useState(100);
  const [waterLevel, setWaterLevel] =
    useState<WaterLevelResponse | null>(null);
  const [pumpLoading, setPumpLoading] = useState(false);
  const [directionPadResetSignal, setDirectionPadResetSignal] = useState(0);
  const pumpRequestInFlightRef = useRef(false);
  const manualDriveDispatcherRef =
    useRef<LatestManualDriveDispatcher | null>(null);

  if (manualDriveDispatcherRef.current === null) {
    manualDriveDispatcherRef.current = new LatestManualDriveDispatcher({
      sendManual: (state) => manualDriveRequests[state](),
      sendEmergencyStop: emergencyStop,
      onSuccess: (state, emergency) => {
        setError(null);
        setStatus(emergency ? "Emergency Stop" : manualDriveLabels[state]);
      },
      onError: (driveError, _state, emergency) => {
        const message =
          driveError instanceof Error
            ? driveError.message
            : emergency
              ? "Emergency stop failed."
              : "Manual drive command failed.";
        setError(message);
        Alert.alert(
          emergency ? "Emergency Stop Error" : "Robot Communication Error",
          message,
        );
      },
    });
  }

  useEffect(() => {
    const loadHardwareState = async () => {
      try {
        setLoading(true);
        const [data, loadedMedicines, loadedWaterLevel] = await Promise.all([
          getRobotHardwareStatus(),
          getMedicines(),
          getWaterLevel().catch(() => null),
        ]);
        const mappedMedicines = loadedMedicines.filter(
          (medicine) => medicine.dispenser_box !== null,
        );
        setStatus(data.status);
        setBattery(data.battery);
        setConnection(data.connection);
        setMode(data.mode);
        setError(data.error ?? null);
        setMedicines(mappedMedicines);
        setWaterLevel(loadedWaterLevel);
        setSelectedMedicine(
          mappedMedicines.length > 0 ? String(mappedMedicines[0].id) : "0",
        );
        if (mappedMedicines.length === 0 && data.error === undefined) {
          setError("No medicine is assigned to a dispenser box.");
        }
      } catch (e) {
        const message =
          e instanceof Error
            ? e.message
            : "Unable to load robot hardware status.";
        setError(message);
        setConnection("Request Failed");
        setStatus("Unavailable");
      } finally {
        setLoading(false);
      }
    };

    loadHardwareState();
  }, []);

  const updateRobotState = async (
    action: () => Promise<MovementResponse>,
    nextStatus: string,
  ) => {
    try {
      setLoading(true);
      setError(null);
      const result = await action();
      if (!result.success) {
        throw new Error("The robot API rejected the command.");
      }
      setStatus(nextStatus);
      const hardware = await getRobotHardwareStatus();
      setConnection(hardware.connection);
      setMode(hardware.mode);
      setError(hardware.error ?? null);
    } catch (e) {
      const message =
        e instanceof Error ? e.message : "Movement command failed.";
      setError(message);
      Alert.alert("Robot Communication Error", message);
    } finally {
      setLoading(false);
    }
  };

  const requireConnectedHardware = (): boolean => {
    if (connection === "Connected") {
      return true;
    }

    const message =
      connection === "Disconnected"
        ? "Hardware Disconnected."
        : "Robot service is unavailable.";
    setError(message);
    Alert.alert("Robot Communication Error", message);
    return false;
  };

  const handleDispenseMedicine = async () => {
    if (!requireConnectedHardware()) return;

    const medicine = medicines.find(
      (item) => String(item.id) === selectedMedicine,
    );
    if (!medicine) {
      setError("Select a mapped medicine before dispensing.");
      return;
    }

    try {
      setLoading(true);
      setError(null);
      await dispenseSelectedMedicine(medicine, medicineQuantity);
      setStatus("Medicine Dispensed");
      Alert.alert(
        "Medicine Dispensed",
        `${medicineQuantity} × ${medicine.name} completed.`,
      );
    } catch (e) {
      const message = e instanceof Error ? e.message : "Dispensing failed.";
      setError(message);
      Alert.alert("Dispensing Error", message);
    } finally {
      setLoading(false);
    }
  };

  const handleDispenseWater = async () => {
    if (!requireConnectedHardware()) return;

    try {
      setLoading(true);
      setError(null);
      await dispenseSelectedWater(waterAmountMl);
      setWaterLevel(await getWaterLevel().catch(() => null));
      setStatus("Water Dispensed");
      Alert.alert(
        "Water Dispensed",
        `${waterAmountMl} ml requested using calibrated pump timing.`,
      );
    } catch (e) {
      const message = e instanceof Error ? e.message : "Water dispensing failed.";
      setError(message);
      Alert.alert("Water Dispensing Error", message);
    } finally {
      setLoading(false);
    }
  };

  const refreshWaterLevel = async () => {
    setWaterLevel(await getWaterLevel().catch(() => null));
  };

  const handleManualPump = async (
    action: () => Promise<{ success: boolean; pump: "ON" | "OFF" }>,
    nextStatus: string,
    refreshAfter: boolean,
  ) => {
    if (
      !requireConnectedHardware() ||
      pumpLoading ||
      pumpRequestInFlightRef.current
    ) {
      return;
    }

    try {
      pumpRequestInFlightRef.current = true;
      setPumpLoading(true);
      setError(null);
      const result = await action();
      if (!result.success) {
        throw new Error("The robot API rejected the pump command.");
      }
      if (refreshAfter) {
        await refreshWaterLevel();
      }
      setStatus(nextStatus);
      Alert.alert("Water Pump", nextStatus);
    } catch (e) {
      const message =
        e instanceof Error ? e.message : "Water pump command failed.";
      setError(message);
      Alert.alert("Water Pump Error", message);
    } finally {
      pumpRequestInFlightRef.current = false;
      setPumpLoading(false);
    }
  };

  const handleManualDriveStateChange = (
    driveState: ManualDriveState,
    force = false,
  ) => {
    manualDriveDispatcherRef.current?.setDesired(driveState, force);
  };

  const handleEmergencyStop = () => {
    setDirectionPadResetSignal((current) => current + 1);
    manualDriveDispatcherRef.current?.emergencyStop();
  };

  const displayedWaterLevel = waterLevelDisplay(waterLevel);

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
          onDriveStateChange={handleManualDriveStateChange}
          resetSignal={directionPadResetSignal}
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
          <View style={styles.navigationTestSection}>
            <Text style={styles.sectionTitle}>Navigation Test</Text>
            <PrimaryButton
              label="Intersection Left"
              onPress={() =>
                updateRobotState(() => intersectionLeft(), "Intersection Left")
              }
              disabled={loading}
              loading={loading}
            />
            <PrimaryButton
              label="Intersection Straight"
              onPress={() =>
                updateRobotState(
                  () => intersectionStraight(),
                  "Intersection Straight",
                )
              }
              disabled={loading}
              loading={loading}
            />
            <PrimaryButton
              label="Intersection Right"
              onPress={() =>
                updateRobotState(
                  () => intersectionRight(),
                  "Intersection Right",
                )
              }
              disabled={loading}
              loading={loading}
            />
            <PrimaryButton
              label="U-Turn"
              onPress={() => updateRobotState(() => uTurn(), "U-Turn")}
              disabled={loading}
              loading={loading}
            />
          </View>
          <PrimaryButton
            label="Emergency Stop"
            onPress={handleEmergencyStop}
            variant="danger"
          />
        </View>

        <View style={styles.controlSection}>
          <Text style={styles.sectionTitle}>Medicine Control</Text>
          <MedicineSelector
            value={selectedMedicine}
            onValueChange={setSelectedMedicine}
            medicines={medicines}
            loading={loading}
          />
          <QuantitySelector
            label="Medicine quantity"
            value={medicineQuantity}
            onDecrease={() =>
              setMedicineQuantity((current) => Math.max(1, current - 1))
            }
            onIncrease={() =>
              setMedicineQuantity((current) => Math.min(10, current + 1))
            }
          />
          <PrimaryButton
            label="Dispense Medicine"
            onPress={handleDispenseMedicine}
            disabled={loading || medicines.length === 0}
            loading={loading}
          />
        </View>

        <View style={styles.controlSection}>
          <Text style={styles.sectionTitle}>Water Control</Text>
          <Text style={styles.calibrationHint}>
            Amount uses the configured measured flow calibration.
          </Text>
          <QuantitySelector
            label="Water amount (ml)"
            value={waterAmountMl}
            onDecrease={() =>
              setWaterAmountMl((current) => Math.max(50, current - 50))
            }
            onIncrease={() =>
              setWaterAmountMl((current) => Math.min(1000, current + 50))
            }
          />
          <PrimaryButton
            label="Dispense Water"
            onPress={handleDispenseWater}
            disabled={loading || pumpLoading}
            loading={loading}
          />
        </View>

        <View style={styles.controlSection}>
          <Text style={styles.sectionTitle}>Water Pump</Text>
          <Text style={styles.calibrationHint}>
            Manual maintenance control. Stop the pump before leaving this screen.
          </Text>
          <PrimaryButton
            label="Start Pump"
            onPress={() =>
              handleManualPump(startManualPump, "Pump Started", false)
            }
            disabled={loading || pumpLoading}
            loading={pumpLoading}
          />
          <PrimaryButton
            label="Stop Pump"
            onPress={() =>
              handleManualPump(stopManualPump, "Pump Stopped", true)
            }
            disabled={loading || pumpLoading}
            loading={pumpLoading}
          />
          <PrimaryButton
            label="Run 5s"
            onPress={() =>
              handleManualPump(() => runManualPump(5), "Pump ran for 5 seconds", true)
            }
            disabled={loading || pumpLoading}
            loading={pumpLoading}
          />
          <PrimaryButton
            label="Run 10s"
            onPress={() =>
              handleManualPump(() => runManualPump(10), "Pump ran for 10 seconds", true)
            }
            disabled={loading || pumpLoading}
            loading={pumpLoading}
          />
        </View>

        {error ? <Text style={styles.errorText}>{error}</Text> : null}

        <View style={styles.statusGrid}>
          <StatusCard label="Robot Status" value={status} />
          <StatusCard
            label="Battery"
            value={battery === null ? "N/A" : `${battery}%`}
          />
          <StatusCard label="Connection" value={connection} />
          <StatusCard label="Mode" value={mode} />
          <StatusCard label="Water Level" value={displayedWaterLevel.value} />
        </View>
        <Text style={styles.waterLevelStatus}>
          Water Status: {displayedWaterLevel.status}
        </Text>
        {displayedWaterLevel.warning ? (
          <Text style={styles.waterLevelWarning}>
            {displayedWaterLevel.warning}
          </Text>
        ) : null}
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
  waterLevelStatus: {
    color: theme.colors.textSecondary,
    marginTop: 12,
  },
  waterLevelWarning: {
    color: theme.colors.emergency,
    marginTop: 4,
  },
  controlSection: {
    marginBottom: 28,
    padding: 18,
    borderRadius: 22,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.card,
  },
  navigationTestSection: {
    gap: 12,
    padding: 18,
    borderRadius: 22,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.card,
  },
  sectionTitle: {
    color: theme.colors.textPrimary,
    fontSize: 22,
    fontWeight: "700",
    marginBottom: 16,
  },
  calibrationHint: {
    color: theme.colors.textSecondary,
    marginBottom: 16,
  },
});
