<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Http\Requests\UpdateRobotStatusRequest;
use App\Http\Resources\RobotStatusResource;
use App\Models\RobotStatus;
use Illuminate\Http\JsonResponse;
use Illuminate\Support\Carbon;

class RobotStatusController extends Controller
{
    public function index(): RobotStatusResource
    {
        $status = RobotStatus::query()->firstOrCreate([], [
            'battery' => 100,
            'status' => 'idle',
            'connected' => false,
            'last_seen' => Carbon::now(),
        ]);

        return new RobotStatusResource($status->load(['currentNode', 'currentMission']));
    }

    public function update(UpdateRobotStatusRequest $request): RobotStatusResource
    {
        $status = RobotStatus::query()->firstOrCreate([], [
            'battery' => 100,
            'status' => 'idle',
            'connected' => false,
            'last_seen' => Carbon::now(),
        ]);

        $payload = $request->validated();
        $payload['last_seen'] = Carbon::now();

        $status->update($payload);

        return new RobotStatusResource($status->fresh()->load(['currentNode', 'currentMission']));
    }
}
