<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('nodes', function (Blueprint $table) {
            $table->id();
            $table->string('node_code')->unique();
            $table->enum('node_type', ['intersection', 'room'])->default('intersection');
            $table->timestamps();
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('nodes');
    }
};
