<?php

namespace App\Services\Mission;

use App\Models\Mission;
use Carbon\CarbonImmutable;
use Carbon\CarbonInterface;
use Illuminate\Database\Eloquent\Builder;
use Illuminate\Support\Facades\DB;
use InvalidArgumentException;

class MissionScheduleService
{
    /**
     * The caller must provide time read from the robot RTC, not phone/server time.
     */
    public function isDue(Mission $mission, CarbonInterface $rtcTime): bool
    {
        $rtcUtc = CarbonImmutable::instance($rtcTime)->utc();

        if (
            $mission->status !== 'pending'
            || $mission->scheduled_at === null
        ) {
            return false;
        }

        return $mission->scheduled_at->utc()->lessThanOrEqualTo($rtcUtc)
            && $this->claimIsAvailable($mission, $rtcUtc);
    }

    /**
     * Atomically reserve the oldest due mission without starting execution.
     */
    public function claimNextDue(CarbonInterface $rtcTime): ?Mission
    {
        $rtcUtc = CarbonImmutable::instance($rtcTime)->utc();
        $staleBefore = $rtcUtc->subSeconds($this->claimLeaseSeconds());

        return DB::transaction(function () use ($rtcUtc, $staleBefore): ?Mission {
            $mission = Mission::query()
                ->where('status', 'pending')
                ->whereNotNull('scheduled_at')
                ->where('scheduled_at', '<=', $rtcUtc)
                ->where(function (Builder $query) use ($staleBefore): void {
                    $query
                        ->whereNull('schedule_claimed_at')
                        ->orWhere('schedule_claimed_at', '<=', $staleBefore);
                })
                ->orderBy('scheduled_at')
                ->orderBy('id')
                ->lockForUpdate()
                ->first();

            if ($mission === null) {
                return null;
            }

            $observedClaimedAt = $mission->schedule_claimed_at?->utc();

            // The conditional update is the final compare-and-set guard. If a
            // competing transaction claimed this row first, this caller gets
            // no mission even on databases where row locks are limited.
            $claimQuery = Mission::query()
                ->whereKey($mission->getKey())
                ->where('status', 'pending')
                ->whereNotNull('scheduled_at')
                ->where('scheduled_at', '<=', $rtcUtc);

            if ($observedClaimedAt === null) {
                $claimQuery->whereNull('schedule_claimed_at');
            } else {
                $claimQuery
                    ->where('schedule_claimed_at', $observedClaimedAt)
                    ->where('schedule_claimed_at', '<=', $staleBefore);
            }

            $claimed = $claimQuery->update(['schedule_claimed_at' => $rtcUtc]);

            if ($claimed !== 1) {
                return null;
            }

            return $mission->fresh(['room.navigationNode', 'medicine']);
        });
    }

    /**
     * Atomically start only the pending mission owned by this exact claim lease.
     */
    public function startClaimedMission(
        Mission $mission,
        CarbonInterface $claimTimestamp,
    ): ?Mission {
        $claimUtc = CarbonImmutable::instance($claimTimestamp)->utc();

        return DB::transaction(function () use ($mission, $claimUtc): ?Mission {
            $updated = Mission::query()
                ->whereKey($mission->getKey())
                ->where('status', 'pending')
                ->where('schedule_claimed_at', $claimUtc)
                ->update(['status' => 'in_progress']);

            if ($updated !== 1) {
                return null;
            }

            return $mission->fresh(['room.navigationNode', 'medicine']);
        });
    }

    private function claimIsAvailable(
        Mission $mission,
        CarbonImmutable $rtcUtc,
    ): bool {
        if ($mission->schedule_claimed_at === null) {
            return true;
        }

        return $mission->schedule_claimed_at->utc()->lessThanOrEqualTo(
            $rtcUtc->subSeconds($this->claimLeaseSeconds()),
        );
    }

    private function claimLeaseSeconds(): int
    {
        $seconds = (int) config('services.robot_api.mission_claim_lease_seconds');

        if ($seconds <= 0) {
            throw new InvalidArgumentException(
                'MISSION_CLAIM_LEASE_SECONDS must be positive.',
            );
        }

        return $seconds;
    }
}
