<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Http\Requests\StoreMissionRequest;
use App\Http\Requests\UpdateMissionRequest;
use App\Http\Resources\MissionResource;
use App\Models\Mission;
use App\Services\Mission\MissionScheduleTime;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Resources\Json\AnonymousResourceCollection;
use Illuminate\Support\Str;

class MissionController extends Controller
{
    public function __construct(
        private readonly MissionScheduleTime $scheduleTime,
    ) {}

    public function index(): AnonymousResourceCollection
    {
        return MissionResource::collection(Mission::query()->with(['room', 'medicine'])->latest()->get());
    }

    public function show(Mission $mission): MissionResource
    {
        return new MissionResource($mission->load(['room', 'medicine']));
    }

    public function store(StoreMissionRequest $request): MissionResource
    {
        $payload = $request->validated();
        $payload['status'] = $this->normalizeStatus($payload['status'] ?? 'pending');
        $this->normalizeScheduledAt($payload);

        $mission = Mission::create($payload);

        return new MissionResource($mission->load(['room', 'medicine']));
    }

    public function update(UpdateMissionRequest $request, Mission $mission): MissionResource
    {
        $payload = $request->validated();

        if (array_key_exists('status', $payload)) {
            $payload['status'] = $this->normalizeStatus($payload['status']);
        }
        $this->normalizeScheduledAt($payload);

        $mission->update($payload);

        return new MissionResource($mission->fresh()->load(['room', 'medicine']));
    }

    public function destroy(Mission $mission): JsonResponse
    {
        $mission->delete();

        return response()->json(null, 204);
    }

    protected function normalizeStatus(string $status): string
    {
        $normalized = Str::lower($status);

        return match ($normalized) {
            'pending' => 'pending',
            'running' => 'in_progress',
            'completed' => 'completed',
            'cancelled' => 'cancelled',
            default => 'pending',
        };
    }

    private function normalizeScheduledAt(array &$payload): void
    {
        if (! array_key_exists('scheduled_at', $payload)) {
            return;
        }

        $payload['schedule_claimed_at'] = null;
        if ($payload['scheduled_at'] === null) {
            return;
        }

        $payload['scheduled_at'] = $this->scheduleTime->localWallClockToUtc(
            $payload['scheduled_at'],
        );
    }
}
