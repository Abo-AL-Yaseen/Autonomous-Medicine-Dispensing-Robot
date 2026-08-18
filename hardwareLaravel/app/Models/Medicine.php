<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Factories\HasFactory;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\HasMany;

class Medicine extends Model
{
    use HasFactory;

    protected $fillable = [
        'name',
        'description',
        'stock_quantity',
        'dispenser_box',
    ];

    protected $casts = [
        'stock_quantity' => 'integer',
        'dispenser_box' => 'integer',
    ];

    public function missions(): HasMany
    {
        return $this->hasMany(Mission::class);
    }

    public function missionItems(): HasMany
    {
        return $this->hasMany(MissionItem::class);
    }
}
