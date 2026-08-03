import { Picker } from "@react-native-picker/picker";
import React from "react";
import { StyleSheet, View } from "react-native";
import { Text } from "react-native-paper";

import { theme } from "@/src/theme/theme";
import { Room } from "@/src/types";

interface RoomSelectorProps {
  value: string;
  onValueChange: (value: string) => void;
  rooms: Room[];
  loading?: boolean;
}

export function RoomSelector({
  value,
  onValueChange,
  rooms,
  loading = false,
}: RoomSelectorProps) {
  return (
    <View style={styles.wrapper}>
      <Text style={styles.label}>Room selector</Text>
      <View style={styles.pickerContainer}>
        <Picker
          enabled={!loading}
          selectedValue={value}
          onValueChange={(itemValue) => onValueChange(String(itemValue))}
          style={styles.picker}
          itemStyle={styles.item}
        >
          {rooms.map((room) => (
            <Picker.Item
              key={room.id}
              label={room.name}
              value={String(room.id)}
            />
          ))}
        </Picker>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: {
    marginBottom: 20,
  },
  label: {
    fontSize: 15,
    fontWeight: "600",
    color: theme.colors.textPrimary,
    marginBottom: 12,
  },
  pickerContainer: {
    backgroundColor: theme.colors.card,
    borderRadius: 22,
    overflow: "hidden",
    borderWidth: 1,
    borderColor: theme.colors.border,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.04,
    shadowRadius: 8,
    elevation: 2,
  },
  picker: {
    height: 56,
    color: theme.colors.textPrimary,
    backgroundColor: theme.colors.card,
  },
  item: {
    fontSize: 16,
  },
});
