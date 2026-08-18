<?php

namespace App\Http\Resources;

use Illuminate\Http\Request;
use Illuminate\Http\Resources\Json\JsonResource;

class MissionResource extends JsonResource
{
    public function toArray(Request $request): array
    {
        return [
            'id' => $this->id,
            'room' => $this->whenLoaded('room') ? new RoomResource($this->room) : [
                'id' => $this->room_id,
            ],
            'medicine' => $this->whenLoaded('medicine') ? new MedicineResource($this->medicine) : [
                'id' => $this->medicine_id,
            ],
            'quantity' => $this->quantity,
            'items' => $this->whenLoaded('items', fn () => $this->items->map(
                fn ($item) => [
                    'id' => $item->id,
                    'medicine' => new MedicineResource($item->medicine),
                    'quantity' => $item->quantity,
                ],
            )->values()),
            'status' => $this->status,
            'scheduled_at' => $this->scheduled_at?->utc()->toIso8601String(),
            'schedule_claimed_at' => $this->schedule_claimed_at?->utc()->toIso8601String(),
            'created_at' => $this->created_at,
            'updated_at' => $this->updated_at,
        ];
    }
}
