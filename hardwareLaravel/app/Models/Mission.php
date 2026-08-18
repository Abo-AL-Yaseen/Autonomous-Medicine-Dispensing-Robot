<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Factories\HasFactory;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\HasMany;

class Mission extends Model
{
    use HasFactory;

    protected $fillable = [
        'room_id',
        'medicine_id',
        'quantity',
        'status',
        'scheduled_at',
        'schedule_claimed_at',
    ];

    protected $casts = [
        'quantity' => 'integer',
        'scheduled_at' => 'datetime',
        'schedule_claimed_at' => 'datetime',
    ];

    public function room(): BelongsTo
    {
        return $this->belongsTo(Room::class);
    }

    public function medicine(): BelongsTo
    {
        return $this->belongsTo(Medicine::class);
    }

    public function items(): HasMany
    {
        return $this->hasMany(MissionItem::class);
    }

    public function robotStatuses(): HasMany
    {
        return $this->hasMany(RobotStatus::class, 'current_mission_id');
    }
}
