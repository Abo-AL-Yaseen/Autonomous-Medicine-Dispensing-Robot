import {
  getApiErrorMessage,
  robotApi,
  unwrapAxiosData,
} from "@/src/config/api";
import { normalizeFastApiManualPump } from "@/src/services/apiAdapters";
import type { ManualPumpResponse } from "@/src/types";

const requestManualPump = async (
  path: string,
  payload?: { seconds: number },
): Promise<ManualPumpResponse> => {
  try {
    const response = await robotApi.post<unknown>(path, payload);
    return normalizeFastApiManualPump(unwrapAxiosData(response));
  } catch (error) {
    throw new Error(
      getApiErrorMessage(error, "Unable to control the water pump."),
    );
  }
};

export const startManualPump = (): Promise<ManualPumpResponse> =>
  requestManualPump("/water/pump/start");

export const stopManualPump = (): Promise<ManualPumpResponse> =>
  requestManualPump("/water/pump/stop");

export const runManualPump = (
  seconds: number,
): Promise<ManualPumpResponse> =>
  requestManualPump("/water/pump/run", { seconds });
