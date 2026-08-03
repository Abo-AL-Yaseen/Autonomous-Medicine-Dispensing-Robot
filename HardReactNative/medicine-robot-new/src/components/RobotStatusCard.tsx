import React from "react";
import { StyleSheet, View } from "react-native";
import { Text } from "react-native-paper";

import RobotIcon from "@/src/assets/RobotIcon";
import { theme } from "@/src/theme/theme";

interface RobotStatusCardProps {
  status: string;
  battery: number;
  location: string;
}

export function RobotStatusCard({
  status,
  battery,
  location,
}: RobotStatusCardProps) {
  return (
    <View style={styles.card}>
      <View style={styles.headerRow}>
        <View>
          <Text style={styles.label}>Robot Status</Text>
          <Text style={styles.status}>{status}</Text>
        </View>
        <View style={styles.batteryPill}>
          <Text style={styles.batteryLabel}>{battery}%</Text>
        </View>
      </View>

      <View style={styles.contentRow}>
        <RobotIcon />
        <View style={styles.metaColumn}>
          <Text style={styles.metaLabel}>Battery</Text>
          <Text style={styles.metaValue}>{battery}%</Text>

          <Text style={styles.metaLabel}>Current Location</Text>
          <Text style={styles.metaValue}>{location}</Text>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: theme.colors.card,
    borderRadius: 28,
    padding: 20,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.06,
    shadowRadius: 15,
    elevation: 5,
  },
  headerRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 10,
  },
  label: {
    fontSize: 13,
    color: theme.colors.textSecondary,
    marginBottom: 4,
  },
  status: {
    fontSize: 26,
    fontWeight: "700",
    color: theme.colors.textPrimary,
  },
  batteryPill: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    backgroundColor: "#EAF8EE",
    borderRadius: 999,
  },
  batteryLabel: {
    fontSize: 14,
    fontWeight: "700",
    color: theme.colors.primary,
  },
  contentRow: {
    flexDirection: "row",
    alignItems: "center",
    marginTop: 4,
  },
  metaColumn: {
    flex: 1,
    marginLeft: 8,
  },
  metaLabel: {
    fontSize: 12,
    color: theme.colors.textSecondary,
    marginTop: 12,
    marginBottom: 4,
  },
  metaValue: {
    fontSize: 19,
    fontWeight: "600",
    color: theme.colors.textPrimary,
  },
});
