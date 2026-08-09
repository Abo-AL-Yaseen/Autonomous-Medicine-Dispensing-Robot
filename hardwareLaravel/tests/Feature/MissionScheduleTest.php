<?php

namespace Tests\Feature;

use App\Models\Medicine;
use App\Models\Mission;
use App\Models\Room;
use App\Services\Mission\MissionScheduleService;
use App\Services\Mission\MissionScheduleTime;
use Carbon\CarbonImmutable;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Validation\ValidationException;
use Tests\TestCase;

class MissionScheduleTest extends TestCase
{
    use RefreshDatabase;

    protected function setUp(): void
    {
        parent::setUp();

        config(['services.robot_api.timezone' => 'Asia/Hebron']);
    }

    public function test_suite_uses_isolated_in_memory_database(): void
    {
        $this->assertSame(
            ':memory:',
            config('database.connections.sqlite.database'),
        );
    }

    public function test_future_pending_mission_is_not_due(): void
    {
        $mission = $this->createMission('pending', '2026-08-09 18:01:00');

        $this->assertFalse($this->service()->isDue(
            $mission,
            CarbonImmutable::parse('2026-08-09 18:00:00', 'UTC'),
        ));
    }

    public function test_exact_time_pending_mission_is_due(): void
    {
        $mission = $this->createMission('pending', '2026-08-09 18:00:00');

        $this->assertTrue($this->service()->isDue(
            $mission,
            CarbonImmutable::parse('2026-08-09 18:00:00', 'UTC'),
        ));
    }

    public function test_overdue_pending_mission_is_due(): void
    {
        $mission = $this->createMission('pending', '2026-08-09 17:00:00');

        $this->assertTrue($this->service()->isDue(
            $mission,
            CarbonImmutable::parse('2026-08-09 18:00:00', 'UTC'),
        ));
    }

    public function test_completed_and_in_progress_missions_are_not_due(): void
    {
        $rtcTime = CarbonImmutable::parse('2026-08-09 18:00:00', 'UTC');

        foreach (['completed', 'in_progress'] as $status) {
            $this->assertFalse($this->service()->isDue(
                $this->createMission($status, '2026-08-09 17:00:00'),
                $rtcTime,
            ));
        }
    }

    public function test_unscheduled_mission_is_not_considered_due(): void
    {
        $mission = $this->createMission('pending', null);

        $this->assertFalse($this->service()->isDue(
            $mission,
            CarbonImmutable::parse('2026-08-09 18:00:00', 'UTC'),
        ));
    }

    public function test_due_mission_can_only_be_claimed_once_without_starting_it(): void
    {
        $mission = $this->createMission('pending', '2026-08-09 17:00:00');
        $rtcTime = CarbonImmutable::parse('2026-08-09 18:00:00', 'UTC');

        $firstClaim = $this->service()->claimNextDue($rtcTime);
        $secondClaim = $this->service()->claimNextDue($rtcTime);

        $this->assertSame($mission->id, $firstClaim?->id);
        $this->assertNull($secondClaim);
        $this->assertSame('pending', $mission->fresh()->status);
        $this->assertNotNull($mission->fresh()->schedule_claimed_at);
    }

    public function test_mission_api_interprets_palestine_schedule_and_stores_utc(): void
    {
        [$room, $medicine] = $this->createRoomAndMedicine();

        $response = $this->postJson('/api/missions', [
            'room_id' => $room->id,
            'medicine_id' => $medicine->id,
            'quantity' => 1,
            'scheduled_at' => '2026-08-09 20:52:00',
        ]);

        $response
            ->assertCreated()
            ->assertJsonPath('data.status', 'pending')
            ->assertJsonPath('data.scheduled_at', '2026-08-09T17:52:00+00:00');
        $this->assertDatabaseHas('missions', [
            'id' => $response->json('data.id'),
            'scheduled_at' => '2026-08-09 17:52:00',
            'status' => 'pending',
        ]);
    }

    public function test_summer_palestine_wall_clock_converts_to_utc(): void
    {
        $utc = $this->scheduleTime()->localWallClockToUtc('2026-08-09 20:52:00');

        $this->assertSame('2026-08-09 17:52:00 +00:00 UTC', $utc->format('Y-m-d H:i:s P e'));
    }

    public function test_winter_palestine_wall_clock_converts_to_utc(): void
    {
        $utc = $this->scheduleTime()->localWallClockToUtc('2026-01-09 20:52:00');

        $this->assertSame('2026-01-09 18:52:00 +00:00 UTC', $utc->format('Y-m-d H:i:s P e'));
    }

    public function test_utc_schedule_converts_back_to_palestine_time(): void
    {
        $local = $this->scheduleTime()->utcToLocal(
            CarbonImmutable::parse('2026-08-09 17:52:00', 'UTC'),
        );

        $this->assertSame(
            '2026-08-09 20:52:00 +03:00 Asia/Hebron',
            $local->format('Y-m-d H:i:s P e'),
        );
    }

    public function test_spring_dst_boundary_uses_timezone_database_rules(): void
    {
        $before = $this->scheduleTime()->localWallClockToUtc('2026-03-28 01:59:00');
        $after = $this->scheduleTime()->localWallClockToUtc('2026-03-28 03:00:00');

        $this->assertSame('2026-03-27 23:59:00', $before->format('Y-m-d H:i:s'));
        $this->assertSame('2026-03-28 00:00:00', $after->format('Y-m-d H:i:s'));
    }

    public function test_nonexistent_spring_dst_wall_clock_is_rejected(): void
    {
        $this->expectException(ValidationException::class);

        $this->scheduleTime()->localWallClockToUtc('2026-03-28 02:30:00');
    }

    public function test_schedule_contract_rejects_timezone_aware_iso_input(): void
    {
        [$room, $medicine] = $this->createRoomAndMedicine();

        $this->postJson('/api/missions', [
            'room_id' => $room->id,
            'medicine_id' => $medicine->id,
            'quantity' => 1,
            'scheduled_at' => '2026-08-09T17:52:00Z',
        ])->assertUnprocessable();
    }

    private function service(): MissionScheduleService
    {
        return app(MissionScheduleService::class);
    }

    private function scheduleTime(): MissionScheduleTime
    {
        return app(MissionScheduleTime::class);
    }

    private function createMission(string $status, ?string $scheduledAt): Mission
    {
        [$room, $medicine] = $this->createRoomAndMedicine();

        return Mission::create([
            'room_id' => $room->id,
            'medicine_id' => $medicine->id,
            'quantity' => 1,
            'status' => $status,
            'scheduled_at' => $scheduledAt,
        ]);
    }

    private function createRoomAndMedicine(): array
    {
        $suffix = (string) Room::query()->count();
        $room = Room::create([
            'room_number' => 'S-'.$suffix,
            'room_name' => 'Schedule Room '.$suffix,
            'description' => null,
        ]);
        $medicine = Medicine::create([
            'name' => 'Schedule Medicine '.$suffix,
            'description' => null,
            'stock_quantity' => 10,
        ]);

        return [$room, $medicine];
    }
}
