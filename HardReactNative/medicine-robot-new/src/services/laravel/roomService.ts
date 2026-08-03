import {
    getApiErrorMessage,
    laravelApi,
    unwrapAxiosData,
} from "@/src/config/api";
import { Room } from "@/src/types";

export const getRooms = async (): Promise<Room[]> => {
  try {
    const response = await laravelApi.get<Room[]>("/rooms");
    return unwrapAxiosData(response);
  } catch (error) {
    throw new Error(getApiErrorMessage(error, "Unable to load rooms."));
  }
};

export const getRoomById = async (roomId: number): Promise<Room> => {
  try {
    const response = await laravelApi.get<Room>(`/rooms/${roomId}`);
    return unwrapAxiosData(response);
  } catch (error) {
    throw new Error(
      getApiErrorMessage(error, `Unable to load room ${roomId}.`),
    );
  }
};

export const createRoom = async (payload: Partial<Room>): Promise<Room> => {
  try {
    const response = await laravelApi.post<Room>("/rooms", payload);
    return unwrapAxiosData(response);
  } catch (error) {
    throw new Error(getApiErrorMessage(error, "Unable to create room."));
  }
};
