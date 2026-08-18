import React, { useCallback, useState } from "react";
import { Alert, Pressable, ScrollView, StyleSheet, View } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import { Text } from "react-native-paper";

import {
  getDispenserStatus,
  setDispenserSlotZero,
} from "@/src/services/robot/dispenserCalibrationService";
import { theme } from "@/src/theme/theme";
import { DispenserDiskStatus, DispenserStatus } from "@/src/types";

interface DiskCardProps {
  box: 1 | 2;
  disk: DispenserDiskStatus | null;
  confirming: boolean;
  onConfirm: (box: 1 | 2) => void;
}

function DiskCard({ box, disk, confirming, onConfirm }: DiskCardProps) {
  return (
    <View style={styles.card}>
      <Text style={styles.cardTitle}>Box {box}</Text>
      <Text style={[styles.status, disk?.calibrated ? styles.calibrated : styles.notCalibrated]}>
        {disk?.calibrated ? "Calibrated ✓" : "Not Calibrated"}
      </Text>
      <Text style={styles.slot}>Current Slot: {disk?.slot ?? "—"}</Text>
      <Text style={styles.instruction}>
        Manually align Slot 0 with the medicine outlet, then confirm.
      </Text>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`Confirm Box ${box} Slot 0`}
        disabled={confirming}
        onPress={() => onConfirm(box)}
        style={({ pressed }) => [
          styles.button,
          confirming && styles.buttonDisabled,
          pressed && !confirming && styles.buttonPressed,
        ]}
      >
        <Text style={styles.buttonText}>
          {confirming ? "Confirming…" : "Confirm Slot 0"}
        </Text>
      </Pressable>
    </View>
  );
}

export default function DispenserSetupScreen() {
  const [status, setStatus] = useState<DispenserStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirmingBox, setConfirmingBox] = useState<1 | 2 | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setStatus(await getDispenserStatus());
    } catch (refreshError) {
      setStatus(null);
      setError(
        refreshError instanceof Error
          ? refreshError.message
          : "Robot dispenser service unavailable.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      void refresh();
    }, [refresh]),
  );

  const confirmSlotZero = async (box: 1 | 2) => {
    setConfirmingBox(box);
    setError(null);
    try {
      await setDispenserSlotZero(box);
      await refresh();
      Alert.alert("Slot confirmed", `Box ${box} is calibrated at Slot 0.`);
    } catch (confirmationError) {
      setError(
        confirmationError instanceof Error
          ? confirmationError.message
          : "Unable to confirm this dispenser slot.",
      );
    } finally {
      setConfirmingBox(null);
    }
  };

  return (
    <View style={styles.safeArea}>
      <ScrollView contentContainerStyle={styles.container}>
        <Text style={styles.title}>Dispenser Setup</Text>
        <Text style={styles.warning}>
          Calibration is required after Arduino reset or power cycle. It does not move the motors.
        </Text>
        {loading ? <Text style={styles.loading}>Loading dispenser status…</Text> : null}
        {error ? (
          <View style={styles.errorCard}>
            <Text style={styles.errorText}>Robot dispenser service unavailable</Text>
            <Text style={styles.errorDetail}>{error}</Text>
            <Pressable accessibilityRole="button" onPress={() => void refresh()} style={styles.retry}>
              <Text style={styles.retryText}>Retry</Text>
            </Pressable>
          </View>
        ) : null}
        {!loading && !error ? (
          <>
            <DiskCard box={1} disk={status?.disk1 ?? null} confirming={confirmingBox === 1} onConfirm={confirmSlotZero} />
            <DiskCard box={2} disk={status?.disk2 ?? null} confirming={confirmingBox === 2} onConfirm={confirmSlotZero} />
          </>
        ) : null}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: theme.colors.background },
  container: { padding: 20, paddingTop: 68, paddingBottom: 40 },
  title: { color: theme.colors.textPrimary, fontSize: 32, fontWeight: "700", marginBottom: 12 },
  warning: { color: theme.colors.textSecondary, fontSize: 14, lineHeight: 20, marginBottom: 20 },
  loading: { color: theme.colors.textSecondary, fontSize: 16 },
  card: { backgroundColor: theme.colors.card, borderRadius: 20, borderColor: theme.colors.border, borderWidth: 1, padding: 18, marginBottom: 16 },
  cardTitle: { color: theme.colors.textPrimary, fontSize: 21, fontWeight: "700" },
  status: { fontSize: 16, fontWeight: "700", marginTop: 10 },
  calibrated: { color: theme.colors.success },
  notCalibrated: { color: theme.colors.emergency },
  slot: { color: theme.colors.textPrimary, fontSize: 16, marginTop: 8 },
  instruction: { color: theme.colors.textSecondary, fontSize: 14, lineHeight: 20, marginTop: 12, marginBottom: 16 },
  button: { backgroundColor: theme.colors.primary, borderRadius: 14, alignItems: "center", paddingVertical: 14 },
  buttonPressed: { opacity: 0.8 },
  buttonDisabled: { opacity: 0.5 },
  buttonText: { color: "#FFFFFF", fontSize: 16, fontWeight: "700" },
  errorCard: { backgroundColor: "#FFF1F0", borderRadius: 18, padding: 16 },
  errorText: { color: theme.colors.emergency, fontSize: 16, fontWeight: "700" },
  errorDetail: { color: theme.colors.textSecondary, marginTop: 6 },
  retry: { alignSelf: "flex-start", marginTop: 14, paddingVertical: 8, paddingHorizontal: 14, borderRadius: 12, backgroundColor: theme.colors.card },
  retryText: { color: theme.colors.primary, fontWeight: "700" },
});
