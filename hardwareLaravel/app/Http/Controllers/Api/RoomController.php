<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Http\Requests\StoreRoomRequest;
use App\Http\Requests\UpdateRoomRequest;
use App\Http\Resources\RoomResource;
use App\Models\Room;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Resources\Json\AnonymousResourceCollection;

class RoomController extends Controller
{
    public function index(): AnonymousResourceCollection
    {
        return RoomResource::collection(Room::query()->with('navigationNode')->latest()->get());
    }

    public function show(Room $room): RoomResource
    {
        return new RoomResource($room->load('navigationNode'));
    }

    public function store(StoreRoomRequest $request): RoomResource
    {
        $room = Room::create($request->validated());

        return new RoomResource($room->load('navigationNode'));
    }

    public function update(UpdateRoomRequest $request, Room $room): RoomResource
    {
        $room->update($request->validated());

        return new RoomResource($room->fresh()->load('navigationNode'));
    }

    public function destroy(Room $room): JsonResponse
    {
        $room->delete();

        return response()->json(null, 204);
    }
}
