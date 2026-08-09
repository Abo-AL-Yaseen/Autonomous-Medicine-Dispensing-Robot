<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Factories\HasFactory;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

class RobotStatus extends Model
{
    use HasFactory;

    protected $table = 'robot_status';

    protected $fillable = [
        'battery',
        'current_node_id',
        'current_mission_id',
        'status',
        'connected',
        'last_seen',
    ];

    protected $casts = [
        'battery' => 'integer',
        'connected' => 'boolean',
        'last_seen' => 'datetime',
    ];

    public function currentNode(): BelongsTo
    {
        return $this->belongsTo(Node::class, 'current_node_id');
    }

    public function currentMission(): BelongsTo
    {
        return $this->belongsTo(Mission::class, 'current_mission_id');
    }
}
