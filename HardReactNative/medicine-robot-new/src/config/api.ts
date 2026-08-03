import axios, { AxiosResponse } from "axios";

const getEnvValue = (key: string, fallback: string): string =>
  process.env[key] ?? fallback;

export const laravelApiBaseUrl = getEnvValue(
  "EXPO_PUBLIC_LARAVEL_API_URL",
  "http://YOUR_PC_IP:8000/api",
);

export const robotApiBaseUrl = getEnvValue(
  "EXPO_PUBLIC_ROBOT_API_URL",
  "http://YOUR_PRIVATE_IP:8000",
);

export const laravelApi = axios.create({
  baseURL: laravelApiBaseUrl,
  timeout: 15000,
  headers: {
    "Content-Type": "application/json",
    Accept: "application/json",
  },
});

export const robotApi = axios.create({
  baseURL: robotApiBaseUrl,
  timeout: 15000,
  headers: {
    "Content-Type": "application/json",
    Accept: "application/json",
  },
});

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null;

export const getApiErrorMessage = (
  error: unknown,
  fallback = "Unable to reach the service. Please try again.",
): string => {
  if (axios.isAxiosError(error)) {
    const status = error.response?.status;
    const responseData = error.response?.data;
    const responseMessage = isRecord(responseData)
      ? typeof responseData.message === "string"
        ? responseData.message
        : null
      : null;

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

    return responseMessage ?? fallback;
  }

  if (error instanceof Error) {
    return error.message || fallback;
  }

  return fallback;
};

export const unwrapAxiosData = <T>(response: AxiosResponse<T>): T =>
  response.data;
