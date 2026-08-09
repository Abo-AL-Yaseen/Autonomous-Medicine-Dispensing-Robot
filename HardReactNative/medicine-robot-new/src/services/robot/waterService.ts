import {
  getApiErrorCode,
  getApiErrorMessage,
  robotApi,
  unwrapAxiosData,
} from "@/src/config/api";
import {
  normalizeFastApiWaterDispense,
  normalizeHardwareActionErrorMessage,
} from "@/src/services/apiAdapters";
import type { WaterDispenseResponse } from "@/src/types";

export const dispenseWater = async (
  amountMl: number,
): Promise<WaterDispenseResponse> => {
  try {
    const response = await robotApi.post<unknown>("/water/dispense", {
      amount_ml: amountMl,
    });
    return normalizeFastApiWaterDispense(unwrapAxiosData(response));
  } catch (error) {
    const fallback = getApiErrorMessage(error, "Unable to dispense water.");
    throw new Error(
      normalizeHardwareActionErrorMessage(getApiErrorCode(error), fallback),
    );
  }
};
