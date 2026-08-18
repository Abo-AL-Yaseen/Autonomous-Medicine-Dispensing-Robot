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
use Illuminate\Support\Facades\DB;

class MissionController extends Controller
{
    public function __construct(
        private readonly MissionScheduleTime $scheduleTime,
    ) {}

    public function index(): AnonymousResourceCollection
    {
        return MissionResource::collection(Mission::query()->with(['room.navigationNode', 'medicine', 'items.medicine'])->latest()->get());
    }

    public function show(Mission $mission): MissionResource
    {
        return new MissionResource($mission->load(['room.navigationNode', 'medicine', 'items.medicine']));
    }

    public function store(StoreMissionRequest $request): MissionResource
    {
        $payload = $request->validated();
        $payload['status'] = $this->normalizeStatus($payload['status'] ?? 'pending');
        $this->normalizeScheduledAt($payload);

        $items = $this->missionItems($payload);
        unset($payload['items']);
        // Keep the original non-null columns as a compatibility projection for
        // deployed databases and older readers; mission_items is authoritative.
        $payload['medicine_id'] = $items[0]['medicine_id'];
        $payload['quantity'] = $items[0]['quantity'];
        $mission = DB::transaction(function () use ($payload, $items): Mission {
            $mission = Mission::create($payload);
            $mission->items()->createMany($items);
            return $mission;
        });

        return new MissionResource($mission->load(['room.navigationNode', 'medicine', 'items.medicine']));
    }

    public function update(UpdateMissionRequest $request, Mission $mission): MissionResource
    {
        $payload = $request->validated();

        if (array_key_exists('status', $payload)) {
            $payload['status'] = $this->normalizeStatus($payload['status']);
        }
        $this->normalizeScheduledAt($payload);

        $items = array_key_exists('items', $payload)
            ? $this->missionItems($payload)
            : null;
        unset($payload['items']);
        if ($items !== null) {
            $payload['medicine_id'] = $items[0]['medicine_id'];
            $payload['quantity'] = $items[0]['quantity'];
        }
        DB::transaction(function () use ($mission, $payload, $items): void {
            $mission->update($payload);
            if ($items !== null) {
                $mission->items()->delete();
                $mission->items()->createMany($items);
            }
        });

        return new MissionResource($mission->fresh()->load(['room.navigationNode', 'medicine', 'items.medicine']));
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

    /** @return array<int, array{medicine_id: int, quantity: int}> */
    private function missionItems(array $payload): array
    {
        if (! isset($payload['items'])) {
            return [[
                'medicine_id' => $payload['medicine_id'],
                'quantity' => $payload['quantity'],
            ]];
        }

        return array_map(
            fn (array $item): array => [
                'medicine_id' => $item['medicine_id'],
                'quantity' => $item['quantity'],
            ],
            $payload['items'],
        );
    }
}
