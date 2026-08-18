import {
  getApiErrorMessage,
  robotApi,
  unwrapAxiosData,
} from "@/src/config/api";
import {
  normalizeDispenserSetZero,
  normalizeDispenserStatus,
} from "@/src/services/apiAdapters";
import {
  DispenserSetZeroResponse,
  DispenserStatus,
} from "@/src/types";

export const DISPENSER_STATUS_ENDPOINT = "/dispenser/status";

export const dispenserSetZeroEndpoint = (boxNumber: 1 | 2): string =>
  `/dispenser/box/${boxNumber}/set-zero`;

export const getDispenserStatus = async (): Promise<DispenserStatus> => {
  try {
    const response = await robotApi.get<unknown>(DISPENSER_STATUS_ENDPOINT);
    return normalizeDispenserStatus(unwrapAxiosData(response));
  } catch (error) {
    throw new Error(
      getApiErrorMessage(error, "Robot dispenser service unavailable."),
    );
  }
};

export const setDispenserSlotZero = async (
  boxNumber: 1 | 2,
): Promise<DispenserSetZeroResponse> => {
  try {
    const response = await robotApi.post<unknown>(
      dispenserSetZeroEndpoint(boxNumber),
    );
    return normalizeDispenserSetZero(unwrapAxiosData(response), boxNumber);
  } catch (error) {
    throw new Error(
      getApiErrorMessage(error, "Unable to confirm this dispenser slot."),
    );
  }
};
