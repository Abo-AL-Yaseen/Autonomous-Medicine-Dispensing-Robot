<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Factories\HasFactory;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\HasMany;
use Illuminate\Database\Eloquent\Relations\HasOne;

class Node extends Model
{
    use HasFactory;

    protected $fillable = [
        'node_code',
        'node_type',
        'marker_id',
    ];

    protected $casts = [
        'marker_id' => 'integer',
    ];

    public function room(): HasOne
    {
        return $this->hasOne(Room::class, 'navigation_node_id');
    }

    public function outgoingConnections(): HasMany
    {
        return $this->hasMany(Connection::class, 'from_node_id');
    }

    public function incomingConnections(): HasMany
    {
        return $this->hasMany(Connection::class, 'to_node_id');
    }

    public function robotStatuses(): HasMany
    {
        return $this->hasMany(RobotStatus::class, 'current_node_id');
    }
}
