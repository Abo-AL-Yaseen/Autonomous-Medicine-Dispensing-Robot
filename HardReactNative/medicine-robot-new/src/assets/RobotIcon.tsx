import React from "react";
import { StyleSheet, View } from "react-native";

import { theme } from "@/src/theme/theme";

export default function RobotIcon() {
  return (
    <View style={styles.robotWrap}>
      <View style={styles.shadow} />
      <View style={styles.robotBody}>
        <View style={styles.sensorRow}>
          <View style={styles.sensor} />
          <View style={styles.sensor} />
        </View>
        <View style={styles.eyeRow}>
          <View style={styles.eye} />
          <View style={styles.eye} />
        </View>
        <View style={styles.armLeft} />
        <View style={styles.armRight} />
        <View style={styles.wheelRow}>
          <View style={styles.wheel} />
          <View style={styles.wheel} />
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  robotWrap: {
    width: 180,
    height: 180,
    alignItems: "center",
    justifyContent: "center",
    position: "relative",
  },
  shadow: {
    position: "absolute",
    bottom: 16,
    width: 150,
    height: 18,
    borderRadius: 999,
    backgroundColor: "rgba(17, 17, 17, 0.08)",
  },
  robotBody: {
    width: 120,
    height: 120,
    borderRadius: 28,
    backgroundColor: "#FFFFFF",
    borderWidth: 2,
    borderColor: "#E5E5EA",
    alignItems: "center",
    justifyContent: "center",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.06,
    shadowRadius: 12,
    elevation: 5,
  },
  sensorRow: {
    position: "absolute",
    top: 18,
    flexDirection: "row",
    width: 52,
    justifyContent: "space-between",
  },
  sensor: {
    width: 12,
    height: 12,
    borderRadius: 999,
    backgroundColor: theme.colors.primary,
  },
  eyeRow: {
    flexDirection: "row",
    width: 70,
    justifyContent: "space-between",
    marginBottom: 8,
  },
  eye: {
    width: 18,
    height: 18,
    borderRadius: 999,
    backgroundColor: "#111111",
  },
  armLeft: {
    position: "absolute",
    left: -12,
    width: 12,
    height: 54,
    borderRadius: 999,
    backgroundColor: "#D9D9DF",
    top: 34,
  },
  armRight: {
    position: "absolute",
    right: -12,
    width: 12,
    height: 54,
    borderRadius: 999,
    backgroundColor: "#D9D9DF",
    top: 34,
  },
  wheelRow: {
    position: "absolute",
    bottom: -10,
    width: 90,
    flexDirection: "row",
    justifyContent: "space-between",
  },
  wheel: {
    width: 18,
    height: 18,
    borderRadius: 999,
    backgroundColor: "#111111",
  },
});
