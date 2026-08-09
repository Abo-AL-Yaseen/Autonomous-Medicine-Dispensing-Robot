<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Http\Requests\StartClaimedMissionRequest;
use App\Http\Resources\MissionResource;
use App\Models\Mission;
use App\Services\Mission\MissionScheduleService;
use Carbon\CarbonImmutable;
use Illuminate\Http\JsonResponse;

class MissionExecutionController extends Controller
{
    public function start(
        StartClaimedMissionRequest $request,
        Mission $mission,
        MissionScheduleService $scheduleService,
    ): JsonResponse {
        $claimTimestamp = CarbonImmutable::parse(
            $request->validated('schedule_claimed_at'),
        )->utc();
        $started = $scheduleService->startClaimedMission(
            $mission,
            $claimTimestamp,
        );

        if ($started === null) {
            return response()->json([
                'success' => false,
                'code' => 'INVALID_MISSION_TRANSITION',
                'message' => 'Mission is not pending or the claim lease no longer matches.',
            ], 409);
        }

        return response()->json([
            'success' => true,
            'mission' => (new MissionResource($started))->resolve($request),
        ]);
    }
}
