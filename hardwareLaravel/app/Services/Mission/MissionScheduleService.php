<?php

namespace App\Services\Mission;

use App\Models\Mission;
use Carbon\CarbonImmutable;
use Carbon\CarbonInterface;
use Illuminate\Support\Facades\DB;

class MissionScheduleService
{
    /**
     * The caller must provide time read from the robot RTC, not phone/server time.
     */
    public function isDue(Mission $mission, CarbonInterface $rtcTime): bool
    {
        if (
            $mission->status !== 'pending'
            || $mission->scheduled_at === null
            || $mission->schedule_claimed_at !== null
        ) {
            return false;
        }

        return $mission->scheduled_at->utc()->lessThanOrEqualTo(
            CarbonImmutable::instance($rtcTime)->utc(),
        );
    }

    /**
     * Atomically reserve the oldest due mission without starting execution.
     */
    public function claimNextDue(CarbonInterface $rtcTime): ?Mission
    {
        $rtcUtc = CarbonImmutable::instance($rtcTime)->utc();

        return DB::transaction(function () use ($rtcUtc): ?Mission {
            $mission = Mission::query()
                ->where('status', 'pending')
                ->whereNotNull('scheduled_at')
                ->whereNull('schedule_claimed_at')
                ->where('scheduled_at', '<=', $rtcUtc)
                ->orderBy('scheduled_at')
                ->orderBy('id')
                ->lockForUpdate()
                ->first();

            if ($mission === null) {
                return null;
            }

            $mission->schedule_claimed_at = $rtcUtc;
            $mission->save();

            return $mission->fresh(['room', 'medicine']);
        });
    }
}
