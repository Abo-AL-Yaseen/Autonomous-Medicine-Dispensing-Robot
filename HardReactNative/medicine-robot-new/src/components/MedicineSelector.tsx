import { Picker } from "@react-native-picker/picker";
import React from "react";
import { StyleSheet, View } from "react-native";
import { Text } from "react-native-paper";

import { theme } from "@/src/theme/theme";
import { Medicine } from "@/src/types";

interface MedicineSelectorProps {
  value: string;
  onValueChange: (value: string) => void;
  medicines: Medicine[];
  loading?: boolean;
}

export function MedicineSelector({
  value,
  onValueChange,
  medicines,
  loading = false,
}: MedicineSelectorProps) {
  return (
    <View style={styles.wrapper}>
      <Text style={styles.label}>Medicine selector</Text>
      <View style={styles.pickerContainer}>
        <Picker
          enabled={!loading}
          selectedValue={value}
          onValueChange={(itemValue) => onValueChange(String(itemValue))}
          style={styles.picker}
          itemStyle={styles.item}
        >
          {medicines.map((medicine) => (
            <Picker.Item
              key={medicine.id}
              label={medicine.name}
              value={String(medicine.id)}
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
