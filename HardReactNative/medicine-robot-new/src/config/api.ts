import { create, isAxiosError, type AxiosResponse } from "axios";

export const laravelApiBaseUrl =
  process.env.EXPO_PUBLIC_LARAVEL_API_URL ?? "http://YOUR_PC_IP:8000/api";

export const robotApiBaseUrl =
  process.env.EXPO_PUBLIC_ROBOT_API_URL ?? "http://YOUR_PRIVATE_IP:8000";

export const robotTimezone =
  process.env.EXPO_PUBLIC_ROBOT_TIMEZONE ?? "Asia/Hebron";

export const laravelApi = create({
  baseURL: laravelApiBaseUrl,
  timeout: 15000,
  headers: {
    "Content-Type": "application/json",
    Accept: "application/json",
  },
});

export const robotApi = create({
  baseURL: robotApiBaseUrl,
  timeout: 15000,
  headers: {
    "Content-Type": "application/json",
    Accept: "application/json",
  },
});

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null;

const getResponseMessage = (responseData: unknown): string | null => {
  if (!isRecord(responseData)) return null;
  if (typeof responseData.message === "string") return responseData.message;
  if (typeof responseData.detail === "string") return responseData.detail;

  if (isRecord(responseData.detail)) {
    const detail = responseData.detail;
    if (typeof detail.message === "string") return detail.message;
    if (typeof detail.code === "string") return detail.code;
  }

  return null;
};

const getResponseCode = (responseData: unknown): string | null => {
  if (!isRecord(responseData)) return null;
  if (typeof responseData.code === "string") return responseData.code;

  if (isRecord(responseData.detail) && typeof responseData.detail.code === "string") {
    return responseData.detail.code;
  }

  return null;
};

export const getApiErrorCode = (error: unknown): string | null =>
  isAxiosError(error) ? getResponseCode(error.response?.data) : null;

export const getApiErrorMessage = (
  error: unknown,
  fallback = "Unable to reach the service. Please try again.",
): string => {
  if (isAxiosError(error)) {
    const status = error.response?.status;
    const responseData = error.response?.data;
    const responseMessage = getResponseMessage(responseData);

    if (error.code === "ECONNABORTED") {
      return "The request timed out. Please check the server connection.";
    }

    if (!error.response) {
      return "Network error. Please check the device connectivity and server URL.";
    }

    if (status === 400) {
      return (
        responseMessage ?? "The request was invalid. Please check your inputs."
      );
    }

    if (status === 404) {
      return "The requested resource was not found.";
    }

    if (status === 422) {
      return (
        responseMessage ??
        "The server rejected the request. Please verify the data."
      );
    }

    if (status === 500) {
      return "The server encountered an internal error. Please try again later.";
    }

    if (status === 503) {
      return responseMessage ?? "The robot hardware service is unavailable.";
    }

    return responseMessage ?? fallback;
  }

  if (error instanceof Error) {
    return error.message || fallback;
  }

  return fallback;
};

export const unwrapAxiosData = <T>(response: AxiosResponse<T>): T =>
  response.data;
