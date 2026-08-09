import React from "react";
import { Pressable, StyleSheet, View } from "react-native";
import { Text } from "react-native-paper";

import { theme } from "@/src/theme/theme";

interface QuantitySelectorProps {
  label?: string;
  value: number;
  onDecrease: () => void;
  onIncrease: () => void;
}

export function QuantitySelector({
  label = "Quantity selector",
  value,
  onDecrease,
  onIncrease,
}: QuantitySelectorProps) {
  return (
    <View style={styles.wrapper}>
      <Text style={styles.label}>{label}</Text>
      <View style={styles.row}>
        <Pressable onPress={onDecrease} style={styles.button}>
          <Text style={styles.buttonText}>−</Text>
        </Pressable>

        <View style={styles.valueWrap}>
          <Text style={styles.value}>{value}</Text>
        </View>

        <Pressable onPress={onIncrease} style={styles.button}>
          <Text style={styles.buttonText}>+</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: {
    marginBottom: 24,
  },
  label: {
    fontSize: 15,
    fontWeight: "600",
    color: theme.colors.textPrimary,
    marginBottom: 12,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 16,
  },
  button: {
    width: 64,
    height: 64,
    borderRadius: 22,
    backgroundColor: theme.colors.card,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: theme.colors.border,
  },
  buttonText: {
    fontSize: 30,
    fontWeight: "400",
    color: theme.colors.textPrimary,
  },
  valueWrap: {
    flex: 1,
    height: 64,
    borderRadius: 22,
    backgroundColor: theme.colors.card,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: theme.colors.border,
  },
  value: {
    fontSize: 24,
    fontWeight: "700",
    color: theme.colors.textPrimary,
  },
});
