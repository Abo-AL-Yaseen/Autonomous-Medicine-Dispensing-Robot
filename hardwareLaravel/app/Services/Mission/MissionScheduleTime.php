<?php

namespace App\Services\Mission;

use Carbon\CarbonImmutable;
use Carbon\CarbonInterface;
use Carbon\Exceptions\InvalidFormatException;
use Illuminate\Validation\ValidationException;

final class MissionScheduleTime
{
    public const WALL_CLOCK_FORMAT = 'Y-m-d H:i:s';

    /**
     * Interpret the API's timezone-naive wall-clock value in Palestine, then
     * convert the resulting instant to UTC for database storage.
     */
    public function localWallClockToUtc(string $wallClock): CarbonImmutable
    {
        try {
            $local = CarbonImmutable::createFromFormat(
                '!'.self::WALL_CLOCK_FORMAT,
                $wallClock,
                $this->timezone(),
            );
        } catch (InvalidFormatException) {
            throw $this->invalidWallClock();
        }

        // Carbon normalizes nonexistent DST times (for example, a skipped
        // spring-forward minute). Reject those instead of silently shifting.
        if ($local->format(self::WALL_CLOCK_FORMAT) !== $wallClock) {
            throw $this->invalidWallClock();
        }

        return $local->utc();
    }

    public function utcToLocal(CarbonInterface $instant): CarbonImmutable
    {
        return CarbonImmutable::instance($instant)
            ->utc()
            ->setTimezone($this->timezone());
    }

    private function timezone(): string
    {
        return (string) config('services.robot_api.timezone');
    }

    private function invalidWallClock(): ValidationException
    {
        return ValidationException::withMessages([
            'scheduled_at' => 'The scheduled time is not valid in Palestine time.',
        ]);
    }
}
