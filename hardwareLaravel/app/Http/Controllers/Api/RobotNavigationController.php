<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Http\Requests\RobotNavigationDecisionRequest;
use App\Http\Requests\RobotNavigationStartRequest;
use App\Http\Requests\RobotNavigationArrivedRequest;
use App\Models\Mission;
use App\Services\Navigation\NavigationService;
use Illuminate\Http\JsonResponse;

class RobotNavigationController extends Controller
{
    public function __construct(
        protected NavigationService $navigationService,
    ) {}

    public function start(RobotNavigationStartRequest $request): JsonResponse
    {
        $mission = Mission::query()->findOrFail($request->validated('mission_id'));

        $this->navigationService->startMission($mission);

        return response()->json([
            'success' => true,
        ]);
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
