import {
  getApiErrorMessage,
  robotApi,
  unwrapAxiosData,
} from "@/src/config/api";
import { normalizeFastApiWaterLevel } from "@/src/services/apiAdapters";
import type { WaterLevelResponse } from "@/src/types";

export interface WaterLevelDisplay {
  value: string;
  status: "OK" | "Low" | "Empty" | "Sensor Error";
  warning: string | null;
}

export const waterLevelMissionError = (
  level: WaterLevelResponse,
): string | null => {
  if (level.status === "EMPTY") {
    return "Water tank is empty. Fill it before starting delivery.";
  }
  if (!level.success || level.status === "SENSOR_ERROR") {
    return "Unable to verify the water level. Check the ultrasonic sensor.";
  }
  return null;
};

export const getWaterLevel = async (): Promise<WaterLevelResponse> => {
  try {
    const response = await robotApi.get<unknown>("/water/level");
    return normalizeFastApiWaterLevel(unwrapAxiosData(response));
  } catch (error) {
    throw new Error(
      getApiErrorMessage(error, "Unable to read the water level."),
    );
  }
};

export const getMissionReadyWaterLevel = async (
  loadWaterLevel: () => Promise<WaterLevelResponse> = getWaterLevel,
): Promise<WaterLevelResponse> => {
  let level: WaterLevelResponse;
  try {
    level = await loadWaterLevel();
  } catch {
    throw new Error(
      "Unable to verify the water level. Check the ultrasonic sensor.",
    );
  }
  const readinessError = waterLevelMissionError(level);
  if (readinessError) throw new Error(readinessError);
  return level;
};

export const waterLevelDisplay = (
  level: WaterLevelResponse | null,
): WaterLevelDisplay => {
  if (level === null || level.status === "SENSOR_ERROR") {
    return {
      value: "N/A",
      status: "Sensor Error",
      warning: "Water-level sensor unavailable.",
    };
  }
  if (level.status === "EMPTY") {
    return {
      value: `${level.percent}%`,
      status: "Empty",
      warning: "Water tank is empty.",
    };
  }
  if (level.status === "LOW") {
    return {
      value: `${level.percent}%`,
      status: "Low",
      warning: "Water level is low.",
    };
  }
  return { value: `${level.percent}%`, status: "OK", warning: null };
};
