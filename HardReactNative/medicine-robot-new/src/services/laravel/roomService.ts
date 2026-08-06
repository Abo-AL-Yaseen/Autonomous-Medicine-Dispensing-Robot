import {
    getApiErrorMessage,
    laravelApi,
    unwrapAxiosData,
} from "@/src/config/api";
import {
  normalizeRoom,
  normalizeRooms,
  toLaravelRoomPayload,
} from "@/src/services/apiAdapters";
import { CreateRoomRequest, Room } from "@/src/types";

export const getRooms = async (): Promise<Room[]> => {
  try {
    const response = await laravelApi.get<unknown>("/rooms");
    return normalizeRooms(unwrapAxiosData(response));
  } catch (error) {
    throw new Error(getApiErrorMessage(error, "Unable to load rooms."));
  }
};

export const getRoomById = async (roomId: number): Promise<Room> => {
  try {
    const response = await laravelApi.get<unknown>(`/rooms/${roomId}`);
    return normalizeRoom(unwrapAxiosData(response));
  } catch (error) {
    throw new Error(
      getApiErrorMessage(error, `Unable to load room ${roomId}.`),
    );
  }
};

export const createRoom = async (payload: CreateRoomRequest): Promise<Room> => {
  try {
    const response = await laravelApi.post<unknown>(
      "/rooms",
      toLaravelRoomPayload(payload),
    );
    return normalizeRoom(unwrapAxiosData(response));
  } catch (error) {
    throw new Error(getApiErrorMessage(error, "Unable to create room."));
  }
};
