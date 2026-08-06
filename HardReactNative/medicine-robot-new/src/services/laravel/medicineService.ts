import {
    getApiErrorMessage,
    laravelApi,
    unwrapAxiosData,
} from "@/src/config/api";
import {
  normalizeMedicine,
  normalizeMedicines,
  toLaravelMedicinePayload,
} from "@/src/services/apiAdapters";
import { CreateMedicineRequest, Medicine } from "@/src/types";

export const getMedicines = async (): Promise<Medicine[]> => {
  try {
    const response = await laravelApi.get<unknown>("/medicines");
    return normalizeMedicines(unwrapAxiosData(response));
  } catch (error) {
    throw new Error(getApiErrorMessage(error, "Unable to load medicines."));
  }
};

export const getMedicineById = async (
  medicineId: number,
): Promise<Medicine> => {
  try {
    const response = await laravelApi.get<unknown>(
      `/medicines/${medicineId}`,
    );
    return normalizeMedicine(unwrapAxiosData(response));
  } catch (error) {
    throw new Error(
      getApiErrorMessage(error, `Unable to load medicine ${medicineId}.`),
    );
  }
};

export const createMedicine = async (
  payload: CreateMedicineRequest,
): Promise<Medicine> => {
  try {
    const response = await laravelApi.post<unknown>(
      "/medicines",
      toLaravelMedicinePayload(payload),
    );
    return normalizeMedicine(unwrapAxiosData(response));
  } catch (error) {
    throw new Error(getApiErrorMessage(error, "Unable to create medicine."));
  }
};
