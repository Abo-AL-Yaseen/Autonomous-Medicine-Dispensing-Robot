import React from "react";
import { StyleSheet, View } from "react-native";
import { Text } from "react-native-paper";

import { theme } from "@/src/theme/theme";

interface StatusCardProps {
  label: string;
  value: string;
  accent?: boolean;
}

export function StatusCard({ label, value, accent = false }: StatusCardProps) {
  return (
    <View style={[styles.card, accent && styles.accentCard]}>
      <Text style={styles.label}>{label}</Text>
      <Text style={[styles.value, accent && styles.accentValue]}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    flex: 1,
    backgroundColor: theme.colors.muted,
    borderRadius: 20,
    paddingHorizontal: 16,
    paddingVertical: 14,
    minHeight: 78,
    justifyContent: "center",
  },
  accentCard: {
    backgroundColor: theme.colors.primary,
  },
  label: {
    fontSize: 12,
    color: theme.colors.textSecondary,
    marginBottom: 6,
    letterSpacing: 0.2,
  },
  value: {
    fontSize: 17,
    fontWeight: "700",
    color: theme.colors.textPrimary,
  },
  accentValue: {
    color: "#FFFFFF",
  },
});
