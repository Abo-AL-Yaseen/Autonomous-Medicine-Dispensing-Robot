<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('connections', function (Blueprint $table) {
            $table->id();
            $table->foreignId('from_node_id')->constrained('nodes')->cascadeOnDelete();
            $table->foreignId('to_node_id')->constrained('nodes')->cascadeOnDelete();
            $table->enum('direction', ['LEFT', 'RIGHT', 'STRAIGHT', 'BACK']);
            $table->timestamps();

            $table->unique(['from_node_id', 'to_node_id', 'direction']);
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('connections');
    }
};
