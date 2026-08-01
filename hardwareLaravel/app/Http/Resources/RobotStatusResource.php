<?php

namespace App\Http\Resources;

use Illuminate\Http\Request;
use Illuminate\Http\Resources\Json\JsonResource;

class RobotStatusResource extends JsonResource
{
    public function toArray(Request $request): array
    {
        return [
            'id' => $this->id,
            'battery' => $this->battery,
            'current_node' => $this->whenLoaded('currentNode') ? new NodeResource($this->currentNode) : ($this->current_node_id ? ['id' => $this->current_node_id] : null),
            'current_mission' => $this->whenLoaded('currentMission') ? new MissionResource($this->currentMission) : ($this->current_mission_id ? ['id' => $this->current_mission_id] : null),
            'connected' => $this->connected,
            'status' => $this->status,
            'last_seen' => $this->last_seen,
            'created_at' => $this->created_at,
            'updated_at' => $this->updated_at,
        ];
    }
}
