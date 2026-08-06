import React, { useEffect, useMemo, useState } from "react";
import { Alert, ScrollView, StyleSheet, View } from "react-native";
import { Text } from "react-native-paper";

import { MedicineSelector } from "@/src/components/MedicineSelector";
import { MissionStatusCard } from "@/src/components/MissionStatusCard";
import { PrimaryButton } from "@/src/components/PrimaryButton";
import { QuantitySelector } from "@/src/components/QuantitySelector";
import { RobotStatusCard } from "@/src/components/RobotStatusCard";
import { RoomSelector } from "@/src/components/RoomSelector";
import { useRobotStatus } from "@/src/hooks/useRobotStatus";
import { startDelivery } from "@/src/services/api";
import { getMedicines } from "@/src/services/laravel/medicineService";
import { getRooms } from "@/src/services/laravel/roomService";
import { theme } from "@/src/theme/theme";
import { Medicine, MissionState, Room } from "@/src/types";

export default function DeliveryScreen() {
  const [rooms, setRooms] = useState<Room[]>([]);
  const [medicines, setMedicines] = useState<Medicine[]>([]);
  const [selectedRoom, setSelectedRoom] = useState("0");
  const [selectedMedicine, setSelectedMedicine] = useState("0");
  const [quantity, setQuantity] = useState(1);
  const [missionState, setMissionState] = useState<MissionState>("Waiting");
  const [loadingRooms, setLoadingRooms] = useState(true);
  const [loadingMedicines, setLoadingMedicines] = useState(true);
  const [creatingMission, setCreatingMission] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  const handleStartDelivery = async () => {
    const roomId = Number(selectedRoom);
    const medicineId = Number(selectedMedicine);

    if (!roomId || !medicineId) {
      setError(
        "Please select a room and medicine before starting the delivery.",
      );
      return;
    }

    try {
      setCreatingMission(true);
      setError(null);
      await startDelivery({
        room_id: roomId,
        medicine_id: medicineId,
        quantity,
      });
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
    } finally {
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

          <PrimaryButton
            label="Start Delivery"
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
});
