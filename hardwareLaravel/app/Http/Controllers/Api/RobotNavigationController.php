<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Http\Requests\RobotNavigationArrivedRequest;
use App\Http\Requests\RobotNavigationDecisionRequest;
use App\Http\Requests\RobotNavigationStartRequest;
use App\Models\Mission;
use App\Services\Navigation\NavigationService;
use App\Services\Robot\RobotHardwareApiService;
use App\Services\Robot\RobotHardwareReadiness;
use Illuminate\Http\JsonResponse;
use Illuminate\Support\Facades\DB;

class RobotNavigationController extends Controller
{
    public function __construct(
        protected NavigationService $navigationService,
        protected RobotHardwareApiService $robotHardwareApiService,
    ) {}

    public function start(RobotNavigationStartRequest $request): JsonResponse
    {
        $mission = Mission::query()->findOrFail($request->validated('mission_id'));

        $readiness = $this->robotHardwareApiService->checkReadiness();

        if ($readiness !== RobotHardwareReadiness::Ready) {
            return $this->readinessErrorResponse($readiness);
        }

        DB::transaction(function () use ($mission): void {
            $this->navigationService->startMission($mission);
        });

        return response()->json([
            'success' => true,
            'message' => 'Robot readiness confirmed. Automatic hardware execution is not implemented yet.',
        ]);
    }

    private function readinessErrorResponse(RobotHardwareReadiness $readiness): JsonResponse
    {
        [$code, $message, $status] = match ($readiness) {
            RobotHardwareReadiness::HardwareUnavailable => [
                'HARDWARE_UNAVAILABLE',
                'Robot hardware is disconnected.',
                409,
            ],
            RobotHardwareReadiness::ApiUnavailable => [
                'ROBOT_API_UNAVAILABLE',
                'Robot service is unavailable.',
                503,
            ],
            RobotHardwareReadiness::InvalidResponse => [
                'INVALID_ROBOT_API_RESPONSE',
                'Robot service returned an invalid response.',
                502,
            ],
            RobotHardwareReadiness::Ready => throw new \LogicException('A ready robot cannot produce an error response.'),
        };

        return response()->json([
            'success' => false,
            'code' => $code,
            'message' => $message,
        ], $status);
    }

    public function decision(RobotNavigationDecisionRequest $request): JsonResponse
    {
        $mission = Mission::query()->findOrFail($request->validated('mission_id'));

        $decision = $this->navigationService->decideAtIntersection(
            $mission,
            $request->validated('current_node'),
            $request->validated('available_nodes'),
        );

        return response()->json($decision);
    }

    public function arrived(RobotNavigationArrivedRequest $request): JsonResponse
    {
        $mission = Mission::query()->findOrFail($request->validated('mission_id'));

        $this->navigationService->completeMission($mission);

        return response()->json([
            'success' => true,
        ]);
    }
}
