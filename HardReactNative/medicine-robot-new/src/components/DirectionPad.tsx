import React, { useEffect, useRef } from "react";
import { Pressable, StyleSheet, View } from "react-native";
import { Text } from "react-native-paper";

import { theme } from "@/src/theme/theme";
import {
  createEmptyHeldDirections,
  HeldDirections,
  ManualDriveState,
  resolveManualDriveState,
} from "@/src/services/robot/manualDriveController";

interface DirectionPadProps {
  onDriveStateChange: (state: ManualDriveState, force?: boolean) => void;
  resetSignal?: number;
}

export function DirectionPad({
  onDriveStateChange,
  resetSignal = 0,
}: DirectionPadProps) {
  const heldDirectionsRef = useRef<HeldDirections>(createEmptyHeldDirections());
  const lastStateRef = useRef<ManualDriveState>("MANUAL_STOP");
  const onDriveStateChangeRef = useRef(onDriveStateChange);
  const previousResetSignalRef = useRef(resetSignal);

  useEffect(() => {
    onDriveStateChangeRef.current = onDriveStateChange;
  }, [onDriveStateChange]);

  useEffect(() => {
    if (previousResetSignalRef.current === resetSignal) return;
    previousResetSignalRef.current = resetSignal;
    heldDirectionsRef.current = createEmptyHeldDirections();
    lastStateRef.current = "MANUAL_STOP";
  }, [resetSignal]);

  const updateHeldDirection = (
    direction: keyof HeldDirections,
    held: boolean,
  ) => {
    const nextHeldDirections = {
      ...heldDirectionsRef.current,
      [direction]: held,
    };
    heldDirectionsRef.current = nextHeldDirections;

    const nextState = resolveManualDriveState(nextHeldDirections);
    if (nextState === lastStateRef.current) return;
    lastStateRef.current = nextState;
    onDriveStateChangeRef.current(nextState);
  };

  const stopManualDrive = () => {
    heldDirectionsRef.current = createEmptyHeldDirections();
    lastStateRef.current = "MANUAL_STOP";
    onDriveStateChangeRef.current("MANUAL_STOP", true);
  };

  return (
    <View style={styles.wrapper}>
      <View style={styles.pad}>
        <Pressable
          onPressIn={() => updateHeldDirection("forward", true)}
          onPressOut={() => updateHeldDirection("forward", false)}
          style={({ pressed }) => [
            styles.controlTop,
            pressed && styles.controlPressed,
          ]}
        >
          <Text style={styles.arrow}>▲</Text>
          <Text style={styles.label}>Forward</Text>
        </Pressable>

        <View style={styles.middleRow}>
          <Pressable
            onPressIn={() => updateHeldDirection("left", true)}
            onPressOut={() => updateHeldDirection("left", false)}
            style={({ pressed }) => [
              styles.controlSide,
              pressed && styles.controlPressed,
            ]}
          >
            <Text style={styles.arrow}>◀</Text>
            <Text style={styles.label}>Left</Text>
          </Pressable>

          <Pressable onPress={stopManualDrive} style={styles.stopButton}>
            <Text style={styles.stopText}>■</Text>
            <Text style={styles.label}>Stop</Text>
          </Pressable>

          <Pressable
            onPressIn={() => updateHeldDirection("right", true)}
            onPressOut={() => updateHeldDirection("right", false)}
            style={({ pressed }) => [
              styles.controlSide,
              pressed && styles.controlPressed,
            ]}
          >
            <Text style={styles.arrow}>▶</Text>
            <Text style={styles.label}>Right</Text>
          </Pressable>
        </View>

        <Pressable
          onPressIn={() => updateHeldDirection("backward", true)}
          onPressOut={() => updateHeldDirection("backward", false)}
          style={({ pressed }) => [
            styles.controlBottom,
            pressed && styles.controlPressed,
          ]}
        >
          <Text style={styles.arrow}>▼</Text>
          <Text style={styles.label}>Backward</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: {
    alignItems: "center",
    marginBottom: 28,
  },
  pad: {
    width: 290,
    backgroundColor: "#F2F2F7",
    borderRadius: 30,
    paddingVertical: 18,
    paddingHorizontal: 12,
    borderWidth: 1,
    borderColor: "#E5E5EA",
  },
  controlTop: {
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 10,
  },
  middleRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  controlSide: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: 14,
  },
  stopButton: {
    width: 96,
    height: 96,
    borderRadius: 30,
    backgroundColor: theme.colors.card,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: theme.colors.border,
    marginHorizontal: 8,
  },
  controlBottom: {
    alignItems: "center",
    justifyContent: "center",
    marginTop: 10,
  },
  controlPressed: {
    opacity: 0.55,
  },
  arrow: {
    fontSize: 30,
    color: theme.colors.textPrimary,
    lineHeight: 34,
  },
  stopText: {
    fontSize: 26,
    color: theme.colors.textPrimary,
    lineHeight: 30,
  },
  label: {
    fontSize: 14,
    color: theme.colors.textPrimary,
    marginTop: 4,
    fontWeight: "600",
  },
});
