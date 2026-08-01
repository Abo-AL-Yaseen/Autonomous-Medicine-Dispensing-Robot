<?php

namespace Tests\Feature;

use App\Models\Connection;
use App\Models\Medicine;
use App\Models\Mission;
use App\Models\Node;
use App\Models\Room;
use App\Services\Navigation\NavigationService;
use App\Services\Navigation\PathFindingService;
use Illuminate\Foundation\Testing\RefreshDatabase;
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

        $service = new NavigationService(new PathFindingService());

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

        $service = new NavigationService(new PathFindingService());

        $this->assertTrue($service->startMission($mission));
        $this->assertSame('in_progress', $mission->fresh()->status);

        $this->assertTrue($service->completeMission($mission));
        $this->assertSame('completed', $mission->fresh()->status);
    }
}
