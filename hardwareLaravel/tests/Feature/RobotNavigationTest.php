<?php

namespace Tests\Feature;

use App\Models\Connection;
use App\Models\Medicine;
use App\Models\Mission;
use App\Models\Node;
use App\Models\RobotStatus;
use App\Models\Room;
use App\Services\Navigation\NavigationService;
use App\Services\Navigation\PathFindingService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Http\Client\ConnectionException;
use Illuminate\Http\Client\Request;
use Illuminate\Support\Facades\Http;
use Tests\TestCase;

class RobotNavigationTest extends TestCase
{
    use RefreshDatabase;

    public function test_it_decides_the_next_direction_from_the_navigation_graph(): void
    {
        $room = Room::create([
            'room_number' => '15',
            'room_name' => 'Ward A',
            'description' => 'Patient room',
        ]);

        $medicine = Medicine::create([
            'name' => 'Paracetamol',
            'description' => 'Pain relief',
            'stock_quantity' => 10,
        ]);

        $mission = Mission::create([
            'room_id' => $room->id,
            'medicine_id' => $medicine->id,
            'quantity' => 2,
            'status' => 'pending',
        ]);

        $node1 = Node::create(['node_code' => 'NODE_1', 'node_type' => 'intersection']);
        $node2 = Node::create(['node_code' => 'NODE_2', 'node_type' => 'intersection']);
        $node5 = Node::create(['node_code' => 'NODE_5', 'node_type' => 'intersection']);
        $roomNode = Node::create(['node_code' => 'ROOM_15', 'node_type' => 'room']);

        Connection::create(['from_node_id' => $node1->id, 'to_node_id' => $node2->id, 'direction' => 'LEFT']);
        Connection::create(['from_node_id' => $node1->id, 'to_node_id' => $node5->id, 'direction' => 'RIGHT']);
        Connection::create(['from_node_id' => $node5->id, 'to_node_id' => $roomNode->id, 'direction' => 'STRAIGHT']);

        $service = new NavigationService(new PathFindingService);

        $decision = $service->decideAtIntersection($mission, 'NODE_1', ['NODE_2', 'NODE_5']);

        $this->assertSame('RIGHT', $decision['direction']);
        $this->assertSame('NODE_5', $decision['next_node']);
    }

    public function test_it_starts_and_marks_a_mission_as_completed(): void
    {
        $room = Room::create([
            'room_number' => '20',
            'room_name' => 'Ward B',
            'description' => 'Room B',
        ]);

        $medicine = Medicine::create([
            'name' => 'Ibuprofen',
            'description' => 'Anti-inflammatory',
            'stock_quantity' => 4,
        ]);

        $mission = Mission::create([
            'room_id' => $room->id,
            'medicine_id' => $medicine->id,
            'quantity' => 1,
            'status' => 'pending',
        ]);

        $service = new NavigationService(new PathFindingService);

        $this->assertTrue($service->startMission($mission));
        $this->assertSame('in_progress', $mission->fresh()->status);

        $this->assertTrue($service->completeMission($mission));
        $this->assertSame('completed', $mission->fresh()->status);
    }

    public function test_navigation_start_proceeds_when_fast_api_reports_connected_hardware(): void
    {
        $this->configureRobotApi();
        Http::fake([
            'http://robot.test/health' => Http::response([
                'status' => 'running',
                'hardware_connected' => true,
            ]),
        ]);
        $mission = $this->createPendingMission();

        $response = $this->postJson('/api/robot/navigation/start', [
            'mission_id' => $mission->id,
        ]);

        $response
            ->assertOk()
            ->assertJsonPath('success', true);
        $this->assertSame('in_progress', $mission->fresh()->status);
        Http::assertSentCount(1);
        Http::assertSent(fn (Request $request): bool => $request->method() === 'GET'
            && $request->url() === 'http://robot.test/health'
        );
    }

    public function test_navigation_start_is_rejected_when_hardware_is_disconnected(): void
    {
        $this->configureRobotApi();
        Http::fake([
            'http://robot.test/health' => Http::response([
                'status' => 'running',
                'hardware_connected' => false,
            ]),
        ]);
        $mission = $this->createPendingMission();
        $robotStatus = $this->createIdleRobotStatus();

        $response = $this->postJson('/api/robot/navigation/start', [
            'mission_id' => $mission->id,
        ]);

        $response
            ->assertStatus(409)
            ->assertJson([
                'success' => false,
                'code' => 'HARDWARE_UNAVAILABLE',
                'message' => 'Robot hardware is disconnected.',
            ]);
        $this->assertFailureLeftStateUnchanged($mission, $robotStatus);
        Http::assertSentCount(1);
    }

    public function test_navigation_start_is_rejected_when_fast_api_is_unreachable(): void
    {
        $this->configureRobotApi();
        $attempts = 0;
        Http::fake(function () use (&$attempts): never {
            $attempts++;
            throw new ConnectionException('Connection failed.');
        });
        $mission = $this->createPendingMission();
        $robotStatus = $this->createIdleRobotStatus();

        $response = $this->postJson('/api/robot/navigation/start', [
            'mission_id' => $mission->id,
        ]);

        $response
            ->assertStatus(503)
            ->assertJson([
                'success' => false,
                'code' => 'ROBOT_API_UNAVAILABLE',
                'message' => 'Robot service is unavailable.',
            ]);
        $this->assertFailureLeftStateUnchanged($mission, $robotStatus);
        $this->assertSame(1, $attempts);
    }

    public function test_navigation_start_is_rejected_for_invalid_fast_api_json(): void
    {
        $this->configureRobotApi();
        Http::fake([
            'http://robot.test/health' => Http::response(
                'not-json',
                200,
                ['Content-Type' => 'application/json'],
            ),
        ]);
        $mission = $this->createPendingMission();
        $robotStatus = $this->createIdleRobotStatus();

        $response = $this->postJson('/api/robot/navigation/start', [
            'mission_id' => $mission->id,
        ]);

        $response
            ->assertStatus(502)
            ->assertJson([
                'success' => false,
                'code' => 'INVALID_ROBOT_API_RESPONSE',
                'message' => 'Robot service returned an invalid response.',
            ]);
        $this->assertFailureLeftStateUnchanged($mission, $robotStatus);
        Http::assertSentCount(1);
    }

    public function test_navigation_start_is_rejected_when_health_payload_has_invalid_types(): void
    {
        $this->configureRobotApi();
        Http::fake([
            'http://robot.test/health' => Http::response([
                'status' => 'running',
                'hardware_connected' => 'false',
            ]),
        ]);
        $mission = $this->createPendingMission();
        $robotStatus = $this->createIdleRobotStatus();

        $response = $this->postJson('/api/robot/navigation/start', [
            'mission_id' => $mission->id,
        ]);

        $response
            ->assertStatus(502)
            ->assertJsonPath('code', 'INVALID_ROBOT_API_RESPONSE');
        $this->assertFailureLeftStateUnchanged($mission, $robotStatus);
        Http::assertSentCount(1);
    }

    private function configureRobotApi(): void
    {
        config([
            'services.robot_api.url' => 'http://robot.test',
            'services.robot_api.connect_timeout' => 0.1,
            'services.robot_api.timeout' => 0.2,
        ]);
    }

    private function createPendingMission(): Mission
    {
        $room = Room::create([
            'room_number' => '30',
            'room_name' => 'Ward C',
            'description' => 'Room C',
        ]);
        $medicine = Medicine::create([
            'name' => 'Aspirin',
            'description' => 'Pain relief',
            'stock_quantity' => 8,
        ]);

        return Mission::create([
            'room_id' => $room->id,
            'medicine_id' => $medicine->id,
            'quantity' => 1,
            'status' => 'pending',
        ]);
    }

    private function createIdleRobotStatus(): RobotStatus
    {
        return RobotStatus::create([
            'battery' => 77,
            'status' => 'idle',
            'connected' => false,
            'last_seen' => now(),
        ]);
    }

    private function assertFailureLeftStateUnchanged(Mission $mission, RobotStatus $robotStatus): void
    {
        $this->assertSame('pending', $mission->fresh()->status);

        $freshRobotStatus = $robotStatus->fresh();
        $this->assertSame('idle', $freshRobotStatus->status);
        $this->assertFalse($freshRobotStatus->connected);
        $this->assertNull($freshRobotStatus->current_mission_id);
        $this->assertSame(77, $freshRobotStatus->battery);
    }
}
