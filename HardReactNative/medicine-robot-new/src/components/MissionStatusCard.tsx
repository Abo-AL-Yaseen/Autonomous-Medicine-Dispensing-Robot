import React from "react";
import { StyleSheet, View } from "react-native";
import { Text } from "react-native-paper";

import { theme } from "@/src/theme/theme";
import { MissionState } from "@/src/types";

interface MissionStatusCardProps {
  state: MissionState;
}

const stateColors: Record<MissionState, string> = {
  Waiting: "#E5E5EA",
  Moving: "#DDEBFF",
  Delivering: "#EAF8EE",
  Returning: "#FFF4D9",
  Completed: "#EAF8EE",
};

const stateTextColors: Record<MissionState, string> = {
  Waiting: "#111111",
  Moving: "#0056D6",
  Delivering: "#1B7A39",
  Returning: "#B26A00",
  Completed: "#1B7A39",
};

export function MissionStatusCard({ state }: MissionStatusCardProps) {
  return (
    <View style={styles.card}>
      <Text style={styles.label}>Mission Status</Text>
      <View style={[styles.badge, { backgroundColor: stateColors[state] }]}>
        <Text style={[styles.badgeText, { color: stateTextColors[state] }]}>
          {state}
        </Text>
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
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.05,
    shadowRadius: 12,
    elevation: 4,
  },
  label: {
    fontSize: 13,
    color: theme.colors.textSecondary,
    marginBottom: 14,
  },
  badge: {
    alignSelf: "flex-start",
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderRadius: 999,
  },
  badgeText: {
    fontSize: 16,
    fontWeight: "700",
  },
});
