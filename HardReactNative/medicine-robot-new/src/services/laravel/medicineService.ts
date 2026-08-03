import {
    getApiErrorMessage,
    laravelApi,
    unwrapAxiosData,
} from "@/src/config/api";
import { Medicine } from "@/src/types";

export const getMedicines = async (): Promise<Medicine[]> => {
  try {
    const response = await laravelApi.get<Medicine[]>("/medicines");
    return unwrapAxiosData(response);
  } catch (error) {
    throw new Error(getApiErrorMessage(error, "Unable to load medicines."));
  }
};

export const getMedicineById = async (
  medicineId: number,
): Promise<Medicine> => {
  try {
    const response = await laravelApi.get<Medicine>(`/medicines/${medicineId}`);
    return unwrapAxiosData(response);
  } catch (error) {
    throw new Error(
      getApiErrorMessage(error, `Unable to load medicine ${medicineId}.`),
    );
  }
};

export const createMedicine = async (
  payload: Partial<Medicine>,
): Promise<Medicine> => {
  try {
    const response = await laravelApi.post<Medicine>("/medicines", payload);
    return unwrapAxiosData(response);
  } catch (error) {
    throw new Error(getApiErrorMessage(error, "Unable to create medicine."));
  }
};
