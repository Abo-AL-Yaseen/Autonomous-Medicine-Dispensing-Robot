import React, { useEffect, useMemo, useRef, useState } from "react";
import { Ionicons } from "@expo/vector-icons";
import { DateTimePickerAndroid } from "@react-native-community/datetimepicker";
import {
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  View,
} from "react-native";
import { Text } from "react-native-paper";

import { MedicineSelector } from "@/src/components/MedicineSelector";
import { MissionStatusCard } from "@/src/components/MissionStatusCard";
import { PrimaryButton } from "@/src/components/PrimaryButton";
import { QuantitySelector } from "@/src/components/QuantitySelector";
import { RobotStatusCard } from "@/src/components/RobotStatusCard";
import { RoomSelector } from "@/src/components/RoomSelector";
import { useRobotStatus } from "@/src/hooks/useRobotStatus";
import { robotTimezone } from "@/src/config/api";
import { buildRobotScheduleDateTime } from "@/src/services/apiAdapters";
import { startDelivery } from "@/src/services/api";
import { getMedicines } from "@/src/services/laravel/medicineService";
import { createMission } from "@/src/services/laravel/missionService";
import { getRooms } from "@/src/services/laravel/roomService";
import {
  createPickerWallClockSelection,
  formatApiScheduleSummary,
  formatFriendlyScheduleDate,
  formatFriendlyScheduleTime,
  formatScheduleDateValue,
  formatScheduleTimeValue,
  isRobotScheduleInPast,
  PickerWallClockSelection,
} from "@/src/services/scheduleDateTime";
import { theme } from "@/src/theme/theme";
import { Medicine, MissionState, Room } from "@/src/types";

export default function DeliveryScreen() {
  const [rooms, setRooms] = useState<Room[]>([]);
  const [medicines, setMedicines] = useState<Medicine[]>([]);
  const [selectedRoom, setSelectedRoom] = useState("0");
  const [selectedMedicine, setSelectedMedicine] = useState("0");
  const [quantity, setQuantity] = useState(1);
  const [missionState, setMissionState] = useState<MissionState>("Waiting");
  const [scheduleForLater, setScheduleForLater] = useState(false);
  const [scheduledDate, setScheduledDate] =
    useState<PickerWallClockSelection | null>(null);
  const [scheduledTime, setScheduledTime] =
    useState<PickerWallClockSelection | null>(null);
  const [scheduleError, setScheduleError] = useState<string | null>(null);
  const [loadingRooms, setLoadingRooms] = useState(true);
  const [loadingMedicines, setLoadingMedicines] = useState(true);
  const [creatingMission, setCreatingMission] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submissionInProgress = useRef(false);

  const robotStatus = useRobotStatus();

  useEffect(() => {
    const loadOptions = async () => {
      try {
        setLoadingRooms(true);
        setLoadingMedicines(true);
        setError(null);

        const [loadedRooms, loadedMedicines] = await Promise.all([
          getRooms(),
          getMedicines(),
        ]);

        setRooms(loadedRooms);
        setMedicines(loadedMedicines);

        if (loadedRooms.length > 0) {
          setSelectedRoom(String(loadedRooms[0].id));
        }

        if (loadedMedicines.length > 0) {
          setSelectedMedicine(String(loadedMedicines[0].id));
        }

        if (loadedRooms.length === 0 && loadedMedicines.length === 0) {
          setError("No rooms or medicines exist.");
        } else if (loadedRooms.length === 0) {
          setError("No rooms exist.");
        } else if (loadedMedicines.length === 0) {
          setError("No medicines exist.");
        }
      } catch (loadError) {
        const message =
          loadError instanceof Error && loadError.message
            ? loadError.message
            : "Unable to load rooms and medicines.";
        setRooms([]);
        setMedicines([]);
        setSelectedRoom("0");
        setSelectedMedicine("0");
        setError(
          message.startsWith("Invalid ")
            ? `Invalid response received: ${message}`
            : `Backend request failed: ${message}`,
        );
      } finally {
        setLoadingRooms(false);
        setLoadingMedicines(false);
      }
    };

    loadOptions();
  }, []);

  const selectedRoomName = useMemo(
    () =>
      rooms.find((room) => String(room.id) === selectedRoom)?.name ??
      "Room not selected",
    [rooms, selectedRoom],
  );

  const selectedMedicineName = useMemo(
    () =>
      medicines.find((medicine) => String(medicine.id) === selectedMedicine)
        ?.name ?? "Medicine not selected",
    [medicines, selectedMedicine],
  );

  const handleDecrease = () =>
    setQuantity((current) => Math.max(1, current - 1));
  const handleIncrease = () =>
    setQuantity((current) => Math.min(9, current + 1));

  const selectedFriendlyDate = scheduledDate
    ? formatFriendlyScheduleDate(scheduledDate)
    : null;
  const selectedFriendlyTime = scheduledTime
    ? formatFriendlyScheduleTime(scheduledTime)
    : null;

  const handleScheduleToggle = (enabled: boolean) => {
    setScheduleForLater(enabled);
    setScheduleError(null);
  };

  const openDatePicker = () => {
    DateTimePickerAndroid.open({
      value: scheduledDate?.value ?? new Date(),
      mode: "date",
      display: "calendar",
      minimumDate: new Date(),
      timeZoneName: robotTimezone,
      onChange: (event, selectedDateValue) => {
        if (event.type !== "set" || !selectedDateValue) return;

        const selection = createPickerWallClockSelection(
          selectedDateValue,
          event.nativeEvent.utcOffset,
        );
        setScheduledDate(selection);
        setScheduleError(null);

        if (
          scheduledTime &&
          isRobotScheduleInPast(
            selection,
            scheduledTime,
            robotTimezone,
          )
        ) {
          setScheduledTime(null);
          setScheduleError("Choose a future time for the selected date.");
        }
      },
    });
  };

  const openTimePicker = () => {
    DateTimePickerAndroid.open({
      value: scheduledTime?.value ?? new Date(),
      mode: "time",
      display: "clock",
      timeZoneName: robotTimezone,
      onChange: (event, selectedTimeValue) => {
        if (event.type !== "set" || !selectedTimeValue) return;

        const selection = createPickerWallClockSelection(
          selectedTimeValue,
          event.nativeEvent.utcOffset,
        );

        if (
          scheduledDate &&
          isRobotScheduleInPast(
            scheduledDate,
            selection,
            robotTimezone,
          )
        ) {
          setScheduledTime(null);
          setScheduleError("Choose a future time for the selected date.");
          return;
        }

        setScheduledTime(selection);
        setScheduleError(null);
      },
    });
  };

  const handleStartDelivery = async () => {
    if (submissionInProgress.current) return;

    const roomId = Number(selectedRoom);
    const medicineId = Number(selectedMedicine);

    if (!roomId || !medicineId) {
      setError(
        "Please select a room and medicine before starting the delivery.",
      );
      return;
    }

    if (scheduleForLater) {
      if (!scheduledDate || !scheduledTime) {
        setScheduleError("Select both a date and time before scheduling.");
        return;
      }

      if (
        isRobotScheduleInPast(
          scheduledDate,
          scheduledTime,
          robotTimezone,
        )
      ) {
        setScheduleError("Choose a date and time in the future.");
        return;
      }
    }

    submissionInProgress.current = true;
    try {
      setCreatingMission(true);
      setError(null);
      setScheduleError(null);
      const payload = {
        room_id: roomId,
        medicine_id: medicineId,
        quantity,
      };

      if (scheduleForLater) {
        // Guarded above before the request is started.
        if (!scheduledDate || !scheduledTime) return;

        const scheduledDateValue = formatScheduleDateValue(scheduledDate);
        const scheduledTimeValue = formatScheduleTimeValue(scheduledTime);
        const scheduledAt = buildRobotScheduleDateTime(
          scheduledDateValue,
          scheduledTimeValue,
        );
        const mission = await createMission({
          ...payload,
          scheduled_at: scheduledAt,
        });
        const confirmedSchedule = mission.scheduled_at
          ? formatApiScheduleSummary(mission.scheduled_at, robotTimezone)
          : `${selectedFriendlyDate} • ${selectedFriendlyTime}`;
        setMissionState("Waiting");
        Alert.alert(
          "Mission Scheduled",
          `Delivery to ${selectedRoomName} is scheduled for ${confirmedSchedule} Palestine time.`,
        );
        return;
      }

      const delivery = await startDelivery(payload);
      if (
        delivery.executor.success !== true ||
        delivery.executor.result !== "STARTED" ||
        delivery.executor.executor.state !== "GOING_TO_ROOM"
      ) {
        throw new Error("FastAPI did not confirm that the mission started.");
      }
      setMissionState("Moving");
      Alert.alert(
        "Mission Started",
        `Delivery to ${selectedRoomName} with ${selectedMedicineName} has started.`,
      );
    } catch (e) {
      const message =
        e instanceof Error
          ? e.message
          : "Unable to start the delivery mission.";
      setError(message);
      setMissionState("Waiting");
      Alert.alert(
        scheduleForLater ? "Mission Not Scheduled" : "Mission Not Started",
        message,
      );
    } finally {
      submissionInProgress.current = false;
      setCreatingMission(false);
    }
  };

  return (
    <View style={styles.safeArea}>
      <ScrollView
        contentContainerStyle={styles.container}
        showsVerticalScrollIndicator={false}
      >
        <Text style={styles.title}>Medicine Delivery</Text>

        <RobotStatusCard
          status={robotStatus.error ? "Unavailable" : robotStatus.status}
          battery={robotStatus.battery || 0}
          location={robotStatus.location || selectedRoomName}
        />

        <View style={styles.sectionBlock}>
          <RoomSelector
            value={selectedRoom}
            onValueChange={setSelectedRoom}
            rooms={rooms}
            loading={loadingRooms}
          />
          <MedicineSelector
            value={selectedMedicine}
            onValueChange={setSelectedMedicine}
            medicines={medicines}
            loading={loadingMedicines}
          />
          <QuantitySelector
            value={quantity}
            onDecrease={handleDecrease}
            onIncrease={handleIncrease}
          />

          <View style={styles.scheduleRow}>
            <View style={styles.scheduleText}>
              <Text style={styles.scheduleLabel}>Schedule for later</Text>
              <Text style={styles.scheduleHint}>
                Uses the DS1302 Palestine wall-clock
              </Text>
            </View>
            <Switch
              value={scheduleForLater}
              onValueChange={handleScheduleToggle}
              trackColor={{ false: theme.colors.border, true: "#A9E8B8" }}
              thumbColor={
                scheduleForLater ? theme.colors.primary : theme.colors.neutral
              }
            />
          </View>

          {scheduleForLater ? (
            <View style={styles.scheduleCard}>
              <View style={styles.robotTimeRow}>
                <Ionicons
                  name="earth-outline"
                  size={16}
                  color={theme.colors.primary}
                />
                <Text style={styles.robotTimeText}>
                  Robot time • Palestine
                </Text>
              </View>

              <View style={styles.scheduleFieldGroup}>
                <Text style={styles.fieldLabel}>Date</Text>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="Select delivery date"
                  onPress={openDatePicker}
                  style={({ pressed }) => [
                    styles.scheduleField,
                    pressed && styles.scheduleFieldPressed,
                  ]}
                >
                  <View style={styles.fieldContent}>
                    <View style={styles.fieldIcon}>
                      <Ionicons
                        name="calendar-outline"
                        size={21}
                        color={theme.colors.primary}
                      />
                    </View>
                    <Text
                      style={[
                        styles.fieldValue,
                        !selectedFriendlyDate && styles.fieldPlaceholder,
                      ]}
                    >
                      {selectedFriendlyDate ?? "Select date"}
                    </Text>
                  </View>
                  <Ionicons
                    name="chevron-forward"
                    size={20}
                    color={theme.colors.textSecondary}
                  />
                </Pressable>
              </View>

              <View style={styles.scheduleFieldGroup}>
                <Text style={styles.fieldLabel}>Time</Text>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="Select delivery time"
                  onPress={openTimePicker}
                  style={({ pressed }) => [
                    styles.scheduleField,
                    pressed && styles.scheduleFieldPressed,
                  ]}
                >
                  <View style={styles.fieldContent}>
                    <View style={styles.fieldIcon}>
                      <Ionicons
                        name="time-outline"
                        size={22}
                        color={theme.colors.primary}
                      />
                    </View>
                    <Text
                      style={[
                        styles.fieldValue,
                        !selectedFriendlyTime && styles.fieldPlaceholder,
                      ]}
                    >
                      {selectedFriendlyTime ?? "Select time"}
                    </Text>
                  </View>
                  <Ionicons
                    name="chevron-forward"
                    size={20}
                    color={theme.colors.textSecondary}
                  />
                </Pressable>
              </View>

              {selectedFriendlyDate && selectedFriendlyTime ? (
                <View style={styles.scheduleSummary}>
                  <Text style={styles.summaryLabel}>Scheduled for</Text>
                  <Text style={styles.summaryValue}>
                    {selectedFriendlyDate} • {selectedFriendlyTime}
                  </Text>
                </View>
              ) : null}

              {scheduleError ? (
                <Text style={styles.scheduleErrorText}>{scheduleError}</Text>
              ) : null}
            </View>
          ) : null}

          <PrimaryButton
            label={scheduleForLater ? "Schedule Delivery" : "Start Delivery Now"}
            onPress={handleStartDelivery}
            disabled={
              creatingMission ||
              loadingRooms ||
              loadingMedicines ||
              rooms.length === 0 ||
              medicines.length === 0
            }
            loading={creatingMission}
          />
          {error ? <Text style={styles.errorText}>{error}</Text> : null}
        </View>

        <View style={styles.bottomSpacer}>
          <MissionStatusCard state={missionState} />
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: theme.colors.background,
  },
  container: {
    paddingHorizontal: 20,
    paddingTop: 70,
    paddingBottom: 40,
  },
  title: {
    fontSize: 36,
    fontWeight: "700",
    color: theme.colors.textPrimary,
    letterSpacing: -0.8,
    marginBottom: 20,
  },
  sectionBlock: {
    marginTop: 22,
  },
  bottomSpacer: {
    marginTop: 22,
  },
  errorText: {
    marginTop: 12,
    color: "#C62828",
    fontWeight: "600",
  },
  scheduleRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 16,
  },
  scheduleText: {
    flex: 1,
    marginRight: 12,
  },
  scheduleLabel: {
    color: theme.colors.textPrimary,
    fontSize: 16,
    fontWeight: "600",
  },
  scheduleHint: {
    color: theme.colors.textSecondary,
    fontSize: 13,
    marginTop: 3,
  },
  scheduleCard: {
    padding: 16,
    marginBottom: 20,
    backgroundColor: theme.colors.card,
    borderWidth: 1,
    borderColor: theme.colors.border,
    borderRadius: 22,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.04,
    shadowRadius: 8,
    elevation: 2,
  },
  robotTimeRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 7,
    marginBottom: 18,
  },
  robotTimeText: {
    color: theme.colors.textSecondary,
    fontSize: 13,
    fontWeight: "600",
  },
  scheduleFieldGroup: {
    marginBottom: 16,
  },
  fieldLabel: {
    color: theme.colors.textPrimary,
    fontSize: 15,
    fontWeight: "600",
    marginBottom: 9,
  },
  scheduleField: {
    minHeight: 58,
    paddingHorizontal: 12,
    borderWidth: 1,
    borderColor: theme.colors.border,
    borderRadius: 16,
    backgroundColor: theme.colors.background,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  scheduleFieldPressed: {
    borderColor: theme.colors.primary,
    backgroundColor: "#F0FBF3",
  },
  fieldContent: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
  },
  fieldIcon: {
    width: 38,
    height: 38,
    borderRadius: 12,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#EAF8EE",
    marginRight: 11,
  },
  fieldValue: {
    flex: 1,
    color: theme.colors.textPrimary,
    fontSize: 16,
    fontWeight: "600",
  },
  fieldPlaceholder: {
    color: theme.colors.textSecondary,
    fontWeight: "500",
  },
  scheduleSummary: {
    backgroundColor: "#EAF8EE",
    borderRadius: 16,
    padding: 14,
    marginTop: 2,
  },
  summaryLabel: {
    color: theme.colors.textSecondary,
    fontSize: 12,
    fontWeight: "600",
    marginBottom: 4,
  },
  summaryValue: {
    color: theme.colors.textPrimary,
    fontSize: 16,
    fontWeight: "700",
  },
  scheduleErrorText: {
    color: "#C62828",
    fontSize: 13,
    fontWeight: "600",
    marginTop: 12,
  },
});
