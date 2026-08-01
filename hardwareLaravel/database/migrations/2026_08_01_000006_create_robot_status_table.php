<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('robot_status', function (Blueprint $table) {
            $table->id();
            $table->unsignedInteger('battery')->default(100);
            $table->foreignId('current_node_id')->nullable()->constrained('nodes')->nullOnDelete();
            $table->foreignId('current_mission_id')->nullable()->constrained('missions')->nullOnDelete();
            $table->enum('status', ['idle', 'moving', 'charging', 'error'])->default('idle');
            $table->boolean('connected')->default(false);
            $table->timestamp('last_seen')->nullable();
            $table->timestamps();
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('robot_status');
    }
};
