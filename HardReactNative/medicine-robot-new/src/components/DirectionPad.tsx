import React from "react";
import { Pressable, StyleSheet, View } from "react-native";
import { Text } from "react-native-paper";

import { theme } from "@/src/theme/theme";

interface DirectionPadProps {
  onForward: () => void;
  onBackward: () => void;
  onLeft: () => void;
  onRight: () => void;
  onStop: () => void;
}

export function DirectionPad({
  onForward,
  onBackward,
  onLeft,
  onRight,
  onStop,
}: DirectionPadProps) {
  return (
    <View style={styles.wrapper}>
      <View style={styles.pad}>
        <Pressable onPress={onForward} style={styles.controlTop}>
          <Text style={styles.arrow}>▲</Text>
          <Text style={styles.label}>Forward</Text>
        </Pressable>

        <View style={styles.middleRow}>
          <Pressable onPress={onLeft} style={styles.controlSide}>
            <Text style={styles.arrow}>◀</Text>
            <Text style={styles.label}>Left</Text>
          </Pressable>

          <Pressable onPress={onStop} style={styles.stopButton}>
            <Text style={styles.stopText}>■</Text>
            <Text style={styles.label}>Stop</Text>
          </Pressable>

          <Pressable onPress={onRight} style={styles.controlSide}>
            <Text style={styles.arrow}>▶</Text>
            <Text style={styles.label}>Right</Text>
          </Pressable>
        </View>

        <Pressable onPress={onBackward} style={styles.controlBottom}>
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
