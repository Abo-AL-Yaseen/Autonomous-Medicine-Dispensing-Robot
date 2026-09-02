import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Ionicons } from "@expo/vector-icons";
import { DateTimePickerAndroid } from "@react-native-community/datetimepicker";
import { useFocusEffect } from "@react-navigation/native";
import { useRouter } from "expo-router";
import {
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  View,
} from "react-native";
import { Text } from "react-native-paper";

import { MissionStatusCard } from "@/src/components/MissionStatusCard";
import { DirectionPad } from "@/src/components/DirectionPad";
import { LiveCameraModal } from "@/src/components/LiveCameraModal";
import { PrimaryButton } from "@/src/components/PrimaryButton";
import { RobotStatusCard } from "@/src/components/RobotStatusCard";
import { RoomSelector } from "@/src/components/RoomSelector";
import { useRobotStatus } from "@/src/hooks/useRobotStatus";
import { robotTimezone } from "@/src/config/api";
import {
  buildRobotScheduleDateTime,
  missionExecutorStatusText,
} from "@/src/services/apiAdapters";
import {
  manualBackward,
  manualBackwardLeft,
  manualBackwardRight,
  manualForward,
  manualForwardLeft,
  manualForwardRight,
  manualLeft,
  manualRight,
  manualStop,
  retryDeliveryStart,
  startDelivery,
} from "@/src/services/api";
import { ImmediateDeliveryStartError } from "@/src/services/deliveryService";
import { requiredDispenserBoxes } from "@/src/services/dispenserReadiness";
import { getMedicines } from "@/src/services/laravel/medicineService";
import { createMission } from "@/src/services/laravel/missionService";
import { getRooms } from "@/src/services/laravel/roomService";
import { getDispenserStatus } from "@/src/services/robot/dispenserCalibrationService";
import {
  cancelManualRecovery,
  getMissionExecutorStatus,
  resumeManualRecovery,
} from "@/src/services/robot/executorService";
import {
  LatestManualDriveDispatcher,
  ManualDriveState,
} from "@/src/services/robot/manualDriveController";
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
import {
  DispenserStatus,
  Medicine,
  MissionExecutorStatus,
  MissionState,
  MovementResponse,
  Room,
} from "@/src/types";

const recoveryDriveRequests: Record<
  ManualDriveState,
  () => Promise<MovementResponse>
> = {
  MANUAL_FORWARD: manualForward,
  MANUAL_BACKWARD: manualBackward,
  MANUAL_LEFT: manualLeft,
  MANUAL_RIGHT: manualRight,
  MANUAL_FORWARD_LEFT: manualForwardLeft,
  MANUAL_FORWARD_RIGHT: manualForwardRight,
  MANUAL_BACKWARD_LEFT: manualBackwardLeft,
  MANUAL_BACKWARD_RIGHT: manualBackwardRight,
  MANUAL_STOP: manualStop,
};

export default function DeliveryScreen() {
  const [cameraVisible, setCameraVisible] = useState(false);
  const [rooms, setRooms] = useState<Room[]>([]);
  const [medicines, setMedicines] = useState<Medicine[]>([]);
  const [selectedRoom, setSelectedRoom] = useState("0");
  const [selectedQuantities, setSelectedQuantities] = useState<Record<number, number>>({});
  const [missionState, setMissionState] = useState<MissionState>("Waiting");
  const [executorStatusDetail, setExecutorStatusDetail] = useState<string | null>(null);
  const [executorStatus, setExecutorStatus] =
    useState<MissionExecutorStatus | null>(null);
  const [manualRecoveryRequestRunning, setManualRecoveryRequestRunning] =
    useState(false);
  const [manualRecoveryError, setManualRecoveryError] =
    useState<string | null>(null);
  const [recoveryPadResetSignal, setRecoveryPadResetSignal] = useState(0);
  const [scheduleForLater, setScheduleForLater] = useState(false);
  const [scheduledDate, setScheduledDate] =
    useState<PickerWallClockSelection | null>(null);
  const [scheduledTime, setScheduledTime] =
    useState<PickerWallClockSelection | null>(null);
  const [scheduleError, setScheduleError] = useState<string | null>(null);
  const [loadingRooms, setLoadingRooms] = useState(true);
  const [loadingMedicines, setLoadingMedicines] = useState(true);
  const [creatingMission, setCreatingMission] = useState(false);
  const [pendingImmediateMissionId, setPendingImmediateMissionId] =
    useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dispenserStatus, setDispenserStatus] = useState<DispenserStatus | null>(null);
  const [loadingDispenserStatus, setLoadingDispenserStatus] = useState(true);
  const [dispenserStatusError, setDispenserStatusError] = useState<string | null>(null);
  const submissionInProgress = useRef(false);
  const recoveryDriveDispatcherRef =
    useRef<LatestManualDriveDispatcher | null>(null);
  const router = useRouter();

  const robotStatus = useRobotStatus();

  if (recoveryDriveDispatcherRef.current === null) {
    recoveryDriveDispatcherRef.current = new LatestManualDriveDispatcher({
      sendManual: (state) => recoveryDriveRequests[state](),
      sendEmergencyStop: manualStop,
      onError: (driveError) => {
        setManualRecoveryError(
          driveError instanceof Error
            ? driveError.message
            : "تعذر إرسال أمر الحركة اليدوية.",
        );
      },
    });
  }

  const manualRecoveryActive =
    executorStatus?.state === "WAITING_FOR_MANUAL_RECOVERY" &&
    executorStatus.manual_recovery_active === true;

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const pollExecutor = async () => {
      try {
        const status = await getMissionExecutorStatus();
        if (cancelled) return;
        setExecutorStatus(status);
        setExecutorStatusDetail(missionExecutorStatusText(status));
        if (status.state === "WAITING_FOR_MANUAL_RECOVERY") {
          setMissionState(
            status.manual_recovery_previous_state === "RETURNING_HOME"
              ? "Returning"
              : "Moving",
          );
        }
        if (status.state === "WAITING_FOR_PICKUP") setMissionState("Delivering");
        if (status.state === "RETURNING_HOME") setMissionState("Returning");
        if (status.state === "ARRIVED_HOME") setMissionState("Completed");
        if (status.state === "IDLE" && missionState === "Waiting") {
          setExecutorStatusDetail(null);
        }
        if (status.state !== "IDLE" && status.state !== "FAILED") {
          timer = setTimeout(pollExecutor, 1000);
        }
      } catch {
        if (!cancelled) timer = setTimeout(pollExecutor, 3000);
      }
    };

    void pollExecutor();
    return () => {
      cancelled = true;
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [missionState]);

  const handleRecoveryDriveStateChange = (
    driveState: ManualDriveState,
    force = false,
  ) => {
    if (!manualRecoveryActive || manualRecoveryRequestRunning) return;
    recoveryDriveDispatcherRef.current?.setDesired(driveState, force);
  };

  const handleResumeManualRecovery = async () => {
    if (!manualRecoveryActive || manualRecoveryRequestRunning) return;
    try {
      setManualRecoveryRequestRunning(true);
      setManualRecoveryError(null);
      const result = await resumeManualRecovery();
      setExecutorStatus(result.executor);
      setRecoveryPadResetSignal((current) => current + 1);
      setMissionState(
        result.executor.state === "RETURNING_HOME" ? "Returning" : "Moving",
      );
    } catch (resumeError) {
      setManualRecoveryError(
        resumeError instanceof Error
          ? resumeError.message
          : "تعذر التحقق من الخط ومتابعة المسار.",
      );
    } finally {
      setManualRecoveryRequestRunning(false);
    }
  };

  const handleCancelManualRecovery = async () => {
    if (!manualRecoveryActive || manualRecoveryRequestRunning) return;
    try {
      setManualRecoveryRequestRunning(true);
      setManualRecoveryError(null);
      const result = await cancelManualRecovery();
      setExecutorStatus(result.executor);
      setRecoveryPadResetSignal((current) => current + 1);
    } catch (cancelError) {
      setManualRecoveryError(
        cancelError instanceof Error
          ? cancelError.message
          : "تعذر إيقاف الاستعادة اليدوية.",
      );
    } finally {
      setManualRecoveryRequestRunning(false);
    }
  };

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
        setSelectedQuantities({});
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

  const refreshDispenserStatus = useCallback(async () => {
    setLoadingDispenserStatus(true);
    setDispenserStatusError(null);
    try {
      setDispenserStatus(await getDispenserStatus());
    } catch (statusError) {
      setDispenserStatus(null);
      setDispenserStatusError(
        statusError instanceof Error
          ? statusError.message
          : "Robot dispenser service unavailable.",
      );
    } finally {
      setLoadingDispenserStatus(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      void refreshDispenserStatus();
    }, [refreshDispenserStatus]),
  );

  const selectedRoomName = useMemo(
    () =>
      rooms.find((room) => String(room.id) === selectedRoom)?.name ??
      "Room not selected",
    [rooms, selectedRoom],
  );

  const selectedItems = useMemo(
    () => medicines.flatMap((medicine) => {
      const quantity = selectedQuantities[medicine.id] ?? 0;
      return quantity > 0 ? [{ medicine_id: medicine.id, quantity }] : [];
    }),
    [medicines, selectedQuantities],
  );

  const setMedicineQuantity = (medicineId: number, quantity: number) => {
    setSelectedQuantities((current) => ({
      ...current,
      [medicineId]: Math.max(0, Math.min(9, quantity)),
    }));
  };

  const requiredBoxes = useMemo(
    () => requiredDispenserBoxes(medicines, selectedItems),
    [medicines, selectedItems],
  );

  const calibrationReadinessError = useMemo(() => {
    if (selectedItems.length === 0) return null;
    if (loadingDispenserStatus) return "Checking dispenser calibration…";
    if (dispenserStatusError || dispenserStatus === null) {
      return "Robot dispenser service unavailable. Open Dispenser Setup and retry.";
    }
    const uncalibratedBox = requiredBoxes.find(
      (box) => !(box === 1 ? dispenserStatus.disk1 : dispenserStatus.disk2).calibrated,
    );
    return uncalibratedBox
      ? `Box ${uncalibratedBox} must be calibrated before starting this mission.`
      : null;
  }, [
    dispenserStatus,
    dispenserStatusError,
    loadingDispenserStatus,
    requiredBoxes,
    selectedItems.length,
  ]);

  const selectedFriendlyDate = scheduledDate
    ? formatFriendlyScheduleDate(scheduledDate)
    : null;
  const selectedFriendlyTime = scheduledTime
    ? formatFriendlyScheduleTime(scheduledTime)
    : null;

  const handleScheduleToggle = (enabled: boolean) => {
    if (enabled && pendingImmediateMissionId !== null) {
      setError("Retry the accepted immediate mission before scheduling another one.");
      return;
    }
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
    if (submissionInProgress.current || manualRecoveryActive) return;

    if (pendingImmediateMissionId !== null && !scheduleForLater) {
      submissionInProgress.current = true;
      try {
        setCreatingMission(true);
        setError(null);
        const executor = await retryDeliveryStart(pendingImmediateMissionId);
        if (
          !executor.success ||
          executor.executor.mission_id !== pendingImmediateMissionId ||
          !["STARTING", "GOING_TO_ROOM"].includes(executor.executor.state)
        ) {
          throw new Error("FastAPI did not confirm that the mission is starting.");
        }
        setPendingImmediateMissionId(null);
        setMissionState("Moving");
        Alert.alert(
          "Mission Started",
          `Delivery to ${selectedRoomName} has started.`,
        );
      } catch (retryError) {
        const message =
          retryError instanceof Error
            ? retryError.message
            : "Unable to retry the accepted mission.";
        if (
          retryError instanceof ImmediateDeliveryStartError &&
          !retryError.retryable
        ) {
          setPendingImmediateMissionId(null);
        }
        setError(message);
        setMissionState("Waiting");
        Alert.alert("Mission Not Started", message);
      } finally {
        submissionInProgress.current = false;
        setCreatingMission(false);
      }
      return;
    }

    const roomId = Number(selectedRoom);
    if (!roomId || selectedItems.length === 0) {
      setError(
        "Please select a room and at least one medicine before starting the delivery.",
      );
      return;
    }

    if (calibrationReadinessError) {
      setError(calibrationReadinessError);
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
        items: selectedItems,
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
        delivery.executor.executor.mission_id !== delivery.mission.id ||
        !["STARTING", "GOING_TO_ROOM"].includes(
          delivery.executor.executor.state,
        )
      ) {
        throw new Error("FastAPI did not confirm that the mission is starting.");
      }
      setPendingImmediateMissionId(null);
      setMissionState("Moving");
      Alert.alert(
        "Mission Started",
        `Delivery to ${selectedRoomName} has started.`,
      );
    } catch (e) {
      if (
        !scheduleForLater &&
        e instanceof ImmediateDeliveryStartError &&
        e.retryable &&
        e.missionId !== null
      ) {
        setPendingImmediateMissionId(e.missionId);
      }
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

        <PrimaryButton
          label="Open Live Camera"
          onPress={() => setCameraVisible(true)}
          style={styles.cameraButton}
        />

        {manualRecoveryActive ? (
          <View style={styles.manualRecoveryCard}>
            <Text style={styles.manualRecoveryWarning}>
              تم فقدان المسار. أعد الروبوت إلى الخط ثم اضغط متابعة.
            </Text>
            <Text style={styles.manualRecoveryCountdown}>
              {executorStatus.manual_recovery_seconds_remaining ?? 0}
            </Text>
            <Text style={styles.manualRecoverySeconds}>ثانية متبقية</Text>
            <DirectionPad
              onDriveStateChange={handleRecoveryDriveStateChange}
              resetSignal={recoveryPadResetSignal}
            />
            <PrimaryButton
              label="متابعة المسار"
              onPress={handleResumeManualRecovery}
              disabled={
                manualRecoveryRequestRunning ||
                executorStatus.manual_recovery_can_resume !== true
              }
              loading={manualRecoveryRequestRunning}
            />
            <PrimaryButton
              label="إيقاف وإلغاء"
              onPress={handleCancelManualRecovery}
              disabled={manualRecoveryRequestRunning}
              variant="danger"
            />
            {manualRecoveryError ? (
              <Text style={styles.manualRecoveryError}>
                {manualRecoveryError}
              </Text>
            ) : null}
          </View>
        ) : null}

        <View style={styles.sectionBlock}>
          <RoomSelector
            value={selectedRoom}
            onValueChange={setSelectedRoom}
            rooms={rooms}
            loading={loadingRooms}
          />
          <View style={styles.medicineList}>
            <Text style={styles.medicineLabel}>Medicines</Text>
            {medicines.map((medicine) => {
              const quantity = selectedQuantities[medicine.id] ?? 0;
              return (
                <View
                  key={medicine.id}
                  style={[
                    styles.medicineCard,
                    quantity > 0 && styles.medicineCardSelected,
                  ]}
                >
                  <View style={styles.medicineDetails}>
                    <Text style={styles.medicineName}>{medicine.name}</Text>
                    <Text style={styles.medicineHint}>
                      {medicine.dispenser_box
                        ? `Dispenser Box ${medicine.dispenser_box}`
                        : "Dispenser Box unavailable"}
                    </Text>
                  </View>
                  <View style={styles.quantityControl}>
                    <Pressable
                      accessibilityRole="button"
                      accessibilityLabel={`Decrease ${medicine.name} quantity`}
                      onPress={() => setMedicineQuantity(medicine.id, quantity - 1)}
                      style={styles.quantityButton}
                    >
                      <Text style={styles.quantityButtonText}>−</Text>
                    </Pressable>
                    <View style={styles.quantityValueWrap}>
                      <Text style={styles.quantityValue}>{quantity}</Text>
                      <Text style={styles.quantityState}>
                        {quantity > 0 ? "Selected" : "Not selected"}
                      </Text>
                    </View>
                    <Pressable
                      accessibilityRole="button"
                      accessibilityLabel={`Increase ${medicine.name} quantity`}
                      onPress={() => setMedicineQuantity(medicine.id, quantity + 1)}
                      style={styles.quantityButton}
                    >
                      <Text style={styles.quantityButtonText}>+</Text>
                    </Pressable>
                  </View>
                </View>
              );
            })}
          </View>

          <View style={styles.selectedSummary}>
            <Text style={styles.selectedSummaryTitle}>Selected medicines</Text>
            {selectedItems.length === 0 ? (
              <Text style={styles.selectedSummaryEmpty}>None selected</Text>
            ) : (
              selectedItems.map((item) => {
                const medicine = medicines.find(
                  (candidate) => candidate.id === item.medicine_id,
                );
                return (
                  <Text key={item.medicine_id} style={styles.selectedSummaryItem}>
                    {medicine?.name ?? "Medicine"} × {item.quantity}
                  </Text>
                );
              })
            )}
          </View>

          {selectedItems.length > 0 ? (
            <View style={styles.readinessCard}>
              <Text style={styles.readinessTitle}>Dispenser Readiness</Text>
              <Text style={styles.readinessWarning}>
                Calibration is required after Arduino reset or power cycle.
              </Text>
              {requiredBoxes.map((box) => {
                const calibrated =
                  box === 1
                    ? dispenserStatus?.disk1.calibrated
                    : dispenserStatus?.disk2.calibrated;
                return (
                  <Text
                    key={box}
                    style={[
                      styles.readinessBox,
                      calibrated ? styles.readinessGood : styles.readinessBad,
                    ]}
                  >
                    Box {box}: {calibrated ? "✓ Calibrated" : "✕ Not Calibrated"}
                  </Text>
                );
              })}
              {calibrationReadinessError ? (
                <Text style={styles.readinessError}>{calibrationReadinessError}</Text>
              ) : null}
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Open Dispenser Setup"
                onPress={() => router.push("/dispenser-setup")}
                style={styles.setupLink}
              >
                <Text style={styles.setupLinkText}>Open Dispenser Setup</Text>
              </Pressable>
            </View>
          ) : null}

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
            label={
              scheduleForLater
                ? "Schedule Delivery"
                : pendingImmediateMissionId !== null
                  ? "Retry Start"
                  : "Start Delivery Now"
            }
            onPress={handleStartDelivery}
            disabled={
              creatingMission ||
              manualRecoveryActive ||
              loadingRooms ||
              loadingMedicines ||
              rooms.length === 0 ||
              medicines.length === 0
              || selectedItems.length === 0
              || calibrationReadinessError !== null
            }
            loading={creatingMission}
          />
          {error ? <Text style={styles.errorText}>{error}</Text> : null}
        </View>

        <View style={styles.bottomSpacer}>
          <MissionStatusCard state={missionState} detail={executorStatusDetail} />
        </View>
      </ScrollView>
      <LiveCameraModal
        visible={cameraVisible}
        onClose={() => setCameraVisible(false)}
      />
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
  manualRecoveryCard: {
    marginTop: 18,
    marginBottom: 22,
    padding: 18,
    borderRadius: 22,
    borderWidth: 2,
    borderColor: theme.colors.emergency,
    backgroundColor: "#FFF4F2",
    gap: 12,
  },
  manualRecoveryWarning: {
    color: theme.colors.emergency,
    fontSize: 18,
    fontWeight: "700",
    lineHeight: 29,
    textAlign: "right",
    writingDirection: "rtl",
  },
  manualRecoveryCountdown: {
    color: theme.colors.emergency,
    fontSize: 48,
    fontWeight: "800",
    textAlign: "center",
  },
  manualRecoverySeconds: {
    color: theme.colors.textSecondary,
    fontSize: 15,
    textAlign: "center",
    writingDirection: "rtl",
  },
  manualRecoveryError: {
    color: theme.colors.emergency,
    fontWeight: "700",
    textAlign: "right",
    writingDirection: "rtl",
  },
  medicineList: {
    marginBottom: 20,
  },
  cameraButton: {
    marginTop: 18,
  },
  medicineLabel: {
    color: theme.colors.textPrimary,
    fontSize: 16,
    fontWeight: "600",
    marginBottom: 10,
  },
  medicineCard: {
    padding: 16,
    marginBottom: 12,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.card,
  },
  medicineCardSelected: {
    borderColor: theme.colors.primary,
    backgroundColor: "#F0FBF3",
  },
  medicineDetails: { flex: 1, marginRight: 12 },
  medicineName: { color: theme.colors.textPrimary, fontSize: 16, fontWeight: "600" },
  medicineHint: { color: theme.colors.textSecondary, fontSize: 13, marginTop: 2 },
  quantityControl: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: 16,
  },
  quantityButton: {
    width: 56,
    height: 56,
    borderRadius: 16,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: theme.colors.background,
    borderWidth: 1,
    borderColor: theme.colors.border,
  },
  quantityButtonText: { color: theme.colors.textPrimary, fontSize: 30 },
  quantityValueWrap: { alignItems: "center", minWidth: 96 },
  quantityValue: { color: theme.colors.textPrimary, fontSize: 34, fontWeight: "800" },
  quantityState: { color: theme.colors.textSecondary, fontSize: 12, fontWeight: "600" },
  selectedSummary: {
    marginBottom: 20,
    padding: 16,
    borderRadius: 18,
    backgroundColor: "#EAF8EE",
  },
  selectedSummaryTitle: { color: theme.colors.textPrimary, fontSize: 16, fontWeight: "700", marginBottom: 6 },
  selectedSummaryItem: { color: theme.colors.textPrimary, fontSize: 15, fontWeight: "600", marginTop: 4 },
  selectedSummaryEmpty: { color: theme.colors.textSecondary, fontSize: 14 },
  readinessCard: {
    marginBottom: 20,
    padding: 16,
    borderRadius: 18,
    backgroundColor: theme.colors.card,
    borderWidth: 1,
    borderColor: theme.colors.border,
  },
  readinessTitle: { color: theme.colors.textPrimary, fontSize: 16, fontWeight: "700" },
  readinessWarning: { color: theme.colors.textSecondary, fontSize: 13, marginTop: 5, marginBottom: 10 },
  readinessBox: { fontSize: 15, fontWeight: "700", marginTop: 4 },
  readinessGood: { color: theme.colors.success },
  readinessBad: { color: theme.colors.emergency },
  readinessError: { color: theme.colors.emergency, fontSize: 13, fontWeight: "600", marginTop: 10 },
  setupLink: { alignSelf: "flex-start", marginTop: 12, paddingVertical: 8 },
  setupLinkText: { color: theme.colors.primary, fontWeight: "700" },
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
