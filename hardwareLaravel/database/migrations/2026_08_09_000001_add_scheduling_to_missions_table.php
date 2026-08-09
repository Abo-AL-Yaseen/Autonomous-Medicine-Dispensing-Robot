<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::table('missions', function (Blueprint $table) {
            $table->dateTime('scheduled_at')->nullable()->index();
            $table->dateTime('schedule_claimed_at')->nullable()->index();
        });
    }

    public function down(): void
    {
        Schema::table('missions', function (Blueprint $table) {
            $table->dropIndex(['scheduled_at']);
            $table->dropIndex(['schedule_claimed_at']);
            $table->dropColumn(['scheduled_at', 'schedule_claimed_at']);
        });
    }
};
