<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Http\Requests\ClaimDueMissionRequest;
use App\Http\Resources\MissionResource;
use App\Services\Mission\MissionScheduleService;
use App\Services\Mission\MissionScheduleTime;
use Illuminate\Http\JsonResponse;

class MissionClaimController extends Controller
{
    public function __invoke(
        ClaimDueMissionRequest $request,
        MissionScheduleService $scheduleService,
        MissionScheduleTime $scheduleTime,
    ): JsonResponse {
        $rtcUtc = $scheduleTime->localWallClockToUtc(
            $request->validated('robot_datetime'),
        );
        $mission = $scheduleService->claimNextDue($rtcUtc);

        return response()->json([
            'success' => true,
            'claimed' => $mission !== null,
            'mission' => $mission === null
                ? null
                : (new MissionResource($mission))->resolve($request),
        ]);
    }
}
