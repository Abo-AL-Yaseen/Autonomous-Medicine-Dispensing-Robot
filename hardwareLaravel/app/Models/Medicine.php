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
    ];

    protected $casts = [
        'stock_quantity' => 'integer',
    ];

    public function missions(): HasMany
    {
        return $this->hasMany(Mission::class);
    }
}
