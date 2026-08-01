<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Http\Requests\StoreMissionRequest;
use App\Http\Requests\UpdateMissionRequest;
use App\Http\Resources\MissionResource;
use App\Models\Mission;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Resources\Json\AnonymousResourceCollection;
use Illuminate\Support\Str;

class MissionController extends Controller
{
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

        $mission = Mission::create($payload);

        return new MissionResource($mission->load(['room', 'medicine']));
    }

    public function update(UpdateMissionRequest $request, Mission $mission): MissionResource
    {
        $payload = $request->validated();

        if (array_key_exists('status', $payload)) {
            $payload['status'] = $this->normalizeStatus($payload['status']);
        }

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
}
