<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Factories\HasFactory;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

class MissionItem extends Model
{
    use HasFactory;

    protected $fillable = ['medicine_id', 'quantity'];

    protected $casts = ['quantity' => 'integer'];

    public function mission(): BelongsTo
    {
        return $this->belongsTo(Mission::class);
    }

    public function medicine(): BelongsTo
    {
        return $this->belongsTo(Medicine::class);
    }
}
