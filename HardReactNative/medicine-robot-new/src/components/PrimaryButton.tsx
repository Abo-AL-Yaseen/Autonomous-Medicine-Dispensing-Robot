import React from "react";
import { Pressable, StyleSheet, ViewStyle } from "react-native";
import { Text } from "react-native-paper";

import { theme } from "@/src/theme/theme";

interface PrimaryButtonProps {
  label: string;
  onPress: () => void;
  variant?: "primary" | "danger";
  style?: ViewStyle;
  disabled?: boolean;
  loading?: boolean;
}

export function PrimaryButton({
  label,
  onPress,
  variant = "primary",
  style,
  disabled = false,
  loading = false,
}: PrimaryButtonProps) {
  const isDanger = variant === "danger";
  const resolvedLabel = loading ? "Loading..." : label;

  return (
    <Pressable
      onPress={disabled || loading ? undefined : onPress}
      style={({ pressed }) => [
        styles.button,
        {
          backgroundColor: isDanger
            ? theme.colors.emergency
            : theme.colors.primary,
          opacity: disabled || loading ? 0.65 : 1,
        },
        pressed && !disabled && !loading && styles.pressed,
        style,
      ]}
    >
      <Text style={styles.label}>{resolvedLabel}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    paddingVertical: 18,
    borderRadius: 26,
    alignItems: "center",
    justifyContent: "center",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.08,
    shadowRadius: 12,
    elevation: 4,
  },
  pressed: {
    opacity: 0.88,
  },
  label: {
    color: "#FFFFFF",
    fontSize: 18,
    fontWeight: "700",
  },
});
