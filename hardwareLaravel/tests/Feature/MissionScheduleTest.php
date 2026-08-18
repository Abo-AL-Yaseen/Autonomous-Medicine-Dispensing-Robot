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

        config([
            'services.robot_api.timezone' => 'Asia/Hebron',
            'services.robot_api.mission_claim_lease_seconds' => 60,
        ]);
    }

    public function test_suite_uses_isolated_in_memory_database(): void
    {
        $this->assertSame(
            ':memory:',
            config('database.connections.sqlite.database'),
        );
    }

    public function test_claim_lease_defaults_to_sixty_seconds(): void
    {
        $this->assertSame(
            60,
            config('services.robot_api.mission_claim_lease_seconds'),
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

    public function test_claim_api_does_not_claim_a_future_mission(): void
    {
        $this->createMission('pending', '2026-08-09 18:01:00');

        $this->claimDue('2026-08-09 21:00:00')
            ->assertOk()
            ->assertExactJson([
                'success' => true,
                'claimed' => false,
                'mission' => null,
            ]);
    }

    public function test_claim_api_claims_an_exact_time_mission_once(): void
    {
        $mission = $this->createMission('pending', '2026-08-09 18:00:00');

        $first = $this->claimDue('2026-08-09 21:00:00');
        $second = $this->claimDue('2026-08-09 21:00:00');

        $first
            ->assertOk()
            ->assertJsonPath('claimed', true)
            ->assertJsonPath('mission.id', $mission->id)
            ->assertJsonPath('mission.status', 'pending')
            ->assertJsonPath(
                'mission.schedule_claimed_at',
                '2026-08-09T18:00:00+00:00',
            );
        $second
            ->assertOk()
            ->assertJsonPath('claimed', false)
            ->assertJsonPath('mission', null);
        $this->assertSame('pending', $mission->fresh()->status);
    }

    public function test_claim_api_claims_an_overdue_pending_mission(): void
    {
        $mission = $this->createMission('pending', '2026-08-09 17:00:00');

        $this->claimDue('2026-08-09 21:00:00')
            ->assertOk()
            ->assertJsonPath('mission.id', $mission->id);
    }

    public function test_claim_api_claims_the_oldest_due_mission_first(): void
    {
        $newer = $this->createMission('pending', '2026-08-09 17:30:00');
        $older = $this->createMission('pending', '2026-08-09 17:00:00');

        $this->claimDue('2026-08-09 21:00:00')
            ->assertOk()
            ->assertJsonPath('mission.id', $older->id);
        $this->assertNull($newer->fresh()->schedule_claimed_at);
    }

    public function test_claim_api_ignores_unscheduled_and_non_pending_missions(): void
    {
        $this->createMission('pending', null);
        $this->createMission('in_progress', '2026-08-09 17:00:00');
        $this->createMission('completed', '2026-08-09 17:00:00');

        $this->claimDue('2026-08-09 21:00:00')
            ->assertOk()
            ->assertJsonPath('claimed', false);
    }

    public function test_claim_api_ignores_an_already_claimed_mission(): void
    {
        $mission = $this->createMission('pending', '2026-08-09 17:00:00');
        $mission->schedule_claimed_at = CarbonImmutable::parse(
            '2026-08-09 17:59:30',
            'UTC',
        );
        $mission->save();

        $this->claimDue('2026-08-09 21:00:00')
            ->assertOk()
            ->assertJsonPath('claimed', false);
    }

    public function test_fresh_claim_is_not_reclaimable_before_lease_expiry(): void
    {
        $mission = $this->createMission('pending', '2026-08-09 17:00:00');
        $claimedAt = CarbonImmutable::parse('2026-08-09 18:00:00', 'UTC');

        $this->assertSame(
            $mission->id,
            $this->service()->claimNextDue($claimedAt)?->id,
        );
        $this->assertNull(
            $this->service()->claimNextDue($claimedAt->addSeconds(59)),
        );
        $this->assertTrue(
            $mission->fresh()->schedule_claimed_at->equalTo($claimedAt),
        );
    }

    public function test_stale_claim_is_reclaimed_and_refreshes_same_mission(): void
    {
        $mission = $this->createMission('pending', '2026-08-09 17:00:00');
        $mission->schedule_claimed_at = CarbonImmutable::parse(
            '2026-08-09 17:59:00',
            'UTC',
        );
        $mission->save();
        $reclaimTime = CarbonImmutable::parse('2026-08-09 18:00:00', 'UTC');

        $reclaimed = $this->service()->claimNextDue($reclaimTime);

        $this->assertSame($mission->id, $reclaimed?->id);
        $this->assertTrue(
            $mission->fresh()->schedule_claimed_at->equalTo($reclaimTime),
        );
        $this->assertSame('pending', $mission->fresh()->status);
    }

    public function test_completed_mission_with_stale_claim_is_never_reclaimable(): void
    {
        $mission = $this->createMission('completed', '2026-08-09 17:00:00');
        $mission->schedule_claimed_at = CarbonImmutable::parse(
            '2026-08-09 16:00:00',
            'UTC',
        );
        $mission->save();

        $this->assertNull($this->service()->claimNextDue(
            CarbonImmutable::parse('2026-08-09 18:00:00', 'UTC'),
        ));
    }

    public function test_in_progress_mission_with_stale_claim_is_never_reclaimable(): void
    {
        $mission = $this->createMission('in_progress', '2026-08-09 17:00:00');
        $mission->schedule_claimed_at = CarbonImmutable::parse(
            '2026-08-09 16:00:00',
            'UTC',
        );
        $mission->save();

        $this->assertNull($this->service()->claimNextDue(
            CarbonImmutable::parse('2026-08-09 18:00:00', 'UTC'),
        ));
    }

    public function test_future_mission_with_stale_claim_is_not_reclaimable(): void
    {
        $mission = $this->createMission('pending', '2026-08-09 18:01:00');
        $mission->schedule_claimed_at = CarbonImmutable::parse(
            '2026-08-09 16:00:00',
            'UTC',
        );
        $mission->save();

        $this->assertNull($this->service()->claimNextDue(
            CarbonImmutable::parse('2026-08-09 18:00:00', 'UTC'),
        ));
    }

    public function test_stale_claim_can_only_be_reclaimed_once_per_lease_window(): void
    {
        $mission = $this->createMission('pending', '2026-08-09 17:00:00');
        $mission->schedule_claimed_at = CarbonImmutable::parse(
            '2026-08-09 16:00:00',
            'UTC',
        );
        $mission->save();
        $rtcTime = CarbonImmutable::parse('2026-08-09 18:00:00', 'UTC');

        $first = $this->service()->claimNextDue($rtcTime);
        $second = $this->service()->claimNextDue($rtcTime);

        $this->assertSame($mission->id, $first?->id);
        $this->assertNull($second);
        $this->assertTrue(
            $mission->fresh()->schedule_claimed_at->equalTo($rtcTime),
        );
    }

    public function test_claim_owner_can_transition_pending_mission_to_in_progress(): void
    {
        $mission = $this->createMission('pending', '2026-08-09 17:00:00');
        $mission->schedule_claimed_at = CarbonImmutable::parse(
            '2026-08-09 18:00:00',
            'UTC',
        );
        $mission->save();

        $this->postJson("/api/missions/{$mission->id}/start-execution", [
            'schedule_claimed_at' => '2026-08-09T18:00:00+00:00',
        ])->assertOk()
            ->assertJsonPath('success', true)
            ->assertJsonPath('mission.id', $mission->id)
            ->assertJsonPath('mission.status', 'in_progress');

        $this->assertSame('in_progress', $mission->fresh()->status);
    }

    public function test_start_execution_rejects_a_replaced_claim_lease(): void
    {
        $mission = $this->createMission('pending', '2026-08-09 17:00:00');
        $mission->schedule_claimed_at = CarbonImmutable::parse(
            '2026-08-09 18:01:00',
            'UTC',
        );
        $mission->save();

        $this->postJson("/api/missions/{$mission->id}/start-execution", [
            'schedule_claimed_at' => '2026-08-09T18:00:00+00:00',
        ])->assertConflict()
            ->assertJsonPath('code', 'INVALID_MISSION_TRANSITION');

        $this->assertSame('pending', $mission->fresh()->status);
    }

    public function test_start_execution_rejects_non_pending_mission(): void
    {
        $mission = $this->createMission('completed', '2026-08-09 17:00:00');
        $mission->schedule_claimed_at = CarbonImmutable::parse(
            '2026-08-09 18:00:00',
            'UTC',
        );
        $mission->save();

        $this->postJson("/api/missions/{$mission->id}/start-execution", [
            'schedule_claimed_at' => '2026-08-09T18:00:00+00:00',
        ])->assertConflict()
            ->assertJsonPath('code', 'INVALID_MISSION_TRANSITION');

        $this->assertSame('completed', $mission->fresh()->status);
    }

    public function test_claim_api_requires_the_configured_timezone(): void
    {
        $this->postJson('/api/missions/claim-due', [
            'robot_datetime' => '2026-08-09 21:00:00',
            'timezone' => 'UTC',
        ])->assertUnprocessable()
            ->assertJsonValidationErrors('timezone');
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

    public function test_mission_api_creates_normalized_multiple_medicine_items(): void
    {
        [$room, $firstMedicine] = $this->createRoomAndMedicine();
        $secondMedicine = Medicine::create([
            'name' => 'Second medicine',
            'description' => null,
            'stock_quantity' => 10,
            'dispenser_box' => 2,
        ]);

        $response = $this->postJson('/api/missions', [
            'room_id' => $room->id,
            'items' => [
                ['medicine_id' => $firstMedicine->id, 'quantity' => 2],
                ['medicine_id' => $secondMedicine->id, 'quantity' => 1],
            ],
        ]);

        $response->assertCreated()
            ->assertJsonPath('data.items.0.medicine.id', $firstMedicine->id)
            ->assertJsonPath('data.items.0.quantity', 2)
            ->assertJsonPath('data.items.1.medicine.id', $secondMedicine->id)
            ->assertJsonPath('data.items.1.quantity', 1);
        $this->assertDatabaseHas('mission_items', [
            'mission_id' => $response->json('data.id'),
            'medicine_id' => $secondMedicine->id,
            'quantity' => 1,
        ]);
    }

    public function test_mission_api_rejects_duplicate_medicine_items(): void
    {
        [$room, $medicine] = $this->createRoomAndMedicine();

        $this->postJson('/api/missions', [
            'room_id' => $room->id,
            'items' => [
                ['medicine_id' => $medicine->id, 'quantity' => 1],
                ['medicine_id' => $medicine->id, 'quantity' => 1],
            ],
        ])->assertUnprocessable()->assertJsonValidationErrors('items.1.medicine_id');
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

    private function claimDue(string $robotDateTime)
    {
        return $this->postJson('/api/missions/claim-due', [
            'robot_datetime' => $robotDateTime,
            'timezone' => 'Asia/Hebron',
        ]);
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
            'dispenser_box' => 1,
        ]);

        return [$room, $medicine];
    }
}
