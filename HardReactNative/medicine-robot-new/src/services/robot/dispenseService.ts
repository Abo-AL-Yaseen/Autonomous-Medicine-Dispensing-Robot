import {
  getApiErrorCode,
  getApiErrorMessage,
  robotApi,
  unwrapAxiosData,
} from "@/src/config/api";
import {
  buildMedicineDispensePayload,
  normalizeFastApiDispense,
  normalizeHardwareActionErrorMessage,
} from "@/src/services/apiAdapters";
import type { Medicine, MedicineDispenseResponse } from "@/src/types";

export const dispenseMedicine = async (
  medicine: Medicine,
  quantity: number,
): Promise<MedicineDispenseResponse> => {
  const payload = buildMedicineDispensePayload(
    medicine.dispenser_box,
    quantity,
  );

  try {
    const response = await robotApi.post<unknown>("/dispense", payload);
    return normalizeFastApiDispense(unwrapAxiosData(response));
  } catch (error) {
    const fallback = getApiErrorMessage(error, "Unable to dispense medicine.");
    throw new Error(
      normalizeHardwareActionErrorMessage(getApiErrorCode(error), fallback),
    );
  }
};
