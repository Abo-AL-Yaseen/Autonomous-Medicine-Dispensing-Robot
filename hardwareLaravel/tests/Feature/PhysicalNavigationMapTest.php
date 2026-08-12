<?php

namespace Tests\Feature;

use App\Models\Connection;
use App\Models\Medicine;
use App\Models\Mission;
use App\Models\Node;
use App\Models\Room;
use App\Services\Navigation\NavigationService;
use App\Services\Navigation\PathFindingService;
use Database\Seeders\PhysicalNavigationMapSeeder;
use Illuminate\Database\QueryException;
use Illuminate\Foundation\Testing\RefreshDatabase;
use PHPUnit\Framework\Attributes\DataProvider;
use Tests\TestCase;

class PhysicalNavigationMapTest extends TestCase
{
    use RefreshDatabase;

    protected function setUp(): void
    {
        parent::setUp();

        $this->seed(PhysicalNavigationMapSeeder::class);
    }

    public function test_it_seeds_the_exact_approved_rooms_nodes_markers_and_connections(): void
    {
        $expectedRoomMappings = [
            '1' => ['Room 1', 'ROOM_1', 11],
            '2' => ['Room 2', 'ROOM_2', 12],
            '3' => ['Room 3', 'ROOM_3', 13],
            '4' => ['Room 4', 'ROOM_4', 14],
            '5' => ['Room 5', 'ROOM_5', 15],
        ];

        $this->assertSame(5, Room::query()->count());

        foreach ($expectedRoomMappings as $roomNumber => [$roomName, $nodeCode, $markerId]) {
            $room = Room::query()
                ->with('navigationNode')
                ->where('room_number', $roomNumber)
                ->firstOrFail();

            $this->assertSame($roomName, $room->room_name);
            $this->assertSame($nodeCode, $room->navigationNode?->node_code);
            $this->assertSame($markerId, $room->navigationNode?->marker_id);
        }

        $this->assertSame([
            'NODE_0' => 0,
            'NODE_1' => 1,
            'NODE_2' => 2,
            'ROOM_1' => 11,
            'ROOM_2' => 12,
            'ROOM_3' => 13,
            'ROOM_4' => 14,
            'ROOM_5' => 15,
        ], Node::query()->orderBy('marker_id')->pluck('marker_id', 'node_code')->all());

        $this->assertSame([
            'NODE_0|NODE_1|STRAIGHT',
            'NODE_0|ROOM_1|LEFT',
            'NODE_1|NODE_2|LEFT',
            'NODE_1|ROOM_4|RIGHT',
            'NODE_1|ROOM_5|STRAIGHT',
            'NODE_2|ROOM_2|RIGHT',
            'NODE_2|ROOM_3|LEFT',
        ], $this->connectionKeys());

        $this->assertFalse(Room::query()->where('room_number', '6')->exists());
        $this->assertFalse(Node::query()->whereIn('node_code', ['HOME', 'J1', 'J2', 'J3', 'J4'])->exists());
    }

    #[DataProvider('approvedRoutes')]
    public function test_path_finding_uses_the_exact_approved_route(int $roomNumber, array $expectedSteps): void
    {
        $mission = $this->missionForRoom($roomNumber);
        $pathFinding = app(PathFindingService::class);
        $navigation = app(NavigationService::class);

        foreach ($expectedSteps as [$fromNode, $direction, $toNode]) {
            $availableNodes = Connection::query()
                ->whereHas('fromNode', fn ($query) => $query->where('node_code', $fromNode))
                ->with('toNode')
                ->get()
                ->pluck('toNode.node_code')
                ->all();

            $this->assertSame($toNode, $pathFinding->nextNodeForMission($mission, $fromNode));
            $this->assertSame([
                'direction' => $direction,
                'next_node' => $toNode,
            ], $navigation->decideAtIntersection($mission, $fromNode, $availableNodes));
        }
    }

    public static function approvedRoutes(): array
    {
        return [
            'Room 1' => [1, [
                ['NODE_0', 'LEFT', 'ROOM_1'],
            ]],
            'Room 2' => [2, [
                ['NODE_0', 'STRAIGHT', 'NODE_1'],
                ['NODE_1', 'LEFT', 'NODE_2'],
                ['NODE_2', 'RIGHT', 'ROOM_2'],
            ]],
            'Room 3' => [3, [
                ['NODE_0', 'STRAIGHT', 'NODE_1'],
                ['NODE_1', 'LEFT', 'NODE_2'],
                ['NODE_2', 'LEFT', 'ROOM_3'],
            ]],
            'Room 4' => [4, [
                ['NODE_0', 'STRAIGHT', 'NODE_1'],
                ['NODE_1', 'RIGHT', 'ROOM_4'],
            ]],
            'Room 5' => [5, [
                ['NODE_0', 'STRAIGHT', 'NODE_1'],
                ['NODE_1', 'STRAIGHT', 'ROOM_5'],
            ]],
        ];
    }

    public static function approvedReturnRoutes(): array
    {
        return [
            '1' => [
                ['ROOM_1', 'U_TURN', 'NODE_0'],
            ],
            '2' => [
                ['ROOM_2', 'U_TURN', 'NODE_2'],
                ['NODE_2', 'LEFT', 'NODE_1'],
                ['NODE_1', 'RIGHT', 'NODE_0'],
            ],
            '3' => [
                ['ROOM_3', 'U_TURN', 'NODE_2'],
                ['NODE_2', 'RIGHT', 'NODE_1'],
                ['NODE_1', 'RIGHT', 'NODE_0'],
            ],
            '4' => [
                ['ROOM_4', 'U_TURN', 'NODE_1'],
                ['NODE_1', 'LEFT', 'NODE_0'],
            ],
            '5' => [
                ['ROOM_5', 'U_TURN', 'NODE_1'],
                ['NODE_1', 'STRAIGHT', 'NODE_0'],
            ],
        ];
    }

    public function test_return_routes_are_laravel_owned_and_reference_official_nodes(): void
    {
        $response = $this->getJson('/api/navigation/map')->assertOk();

        $actual = collect($response->json('return_routes'))
            ->mapWithKeys(fn (array $route): array => [
                $route['room_number'] => collect($route['steps'])
                    ->map(fn (array $step): array => [
                        $step['from_node'],
                        $step['direction'],
                        $step['to_node'],
                    ])
                    ->all(),
            ])
            ->all();

        $this->assertSame(self::approvedReturnRoutes(), $actual);

        $nodeCodes = Node::query()->pluck('node_code')->all();
        foreach ($response->json('return_routes') as $route) {
            foreach ($route['steps'] as $step) {
                $this->assertContains($step['from_node'], $nodeCodes);
                $this->assertContains($step['to_node'], $nodeCodes);
            }
        }
    }

    public function test_room_api_exposes_its_navigation_node_and_marker(): void
    {
        $room = Room::query()->where('room_number', '3')->firstOrFail();

        $this->getJson('/api/rooms/'.$room->id)
            ->assertOk()
            ->assertJsonPath('data.id', $room->id)
            ->assertJsonPath('data.room_number', '3')
            ->assertJsonPath('data.room_name', 'Room 3')
            ->assertJsonPath('data.navigation_node.name', 'ROOM_3')
            ->assertJsonPath('data.navigation_node.marker_id', 13);
    }

    public function test_read_only_navigation_map_api_exposes_the_official_contract(): void
    {
        $countsBefore = [
            Room::query()->count(),
            Node::query()->count(),
            Connection::query()->count(),
        ];

        $response = $this->getJson('/api/navigation/map');

        $response
            ->assertOk()
            ->assertJsonPath('success', true)
            ->assertJsonCount(5, 'rooms')
            ->assertJsonCount(8, 'nodes')
            ->assertJsonCount(7, 'connections')
            ->assertJsonCount(5, 'return_routes')
            ->assertJsonPath('rooms.3.room_number', '4')
            ->assertJsonPath('rooms.3.destination_node.node_name', 'ROOM_4')
            ->assertJsonPath('rooms.3.destination_node.marker_id', 14);

        $this->assertSame([
            ['from_node' => 'NODE_0', 'to_node' => 'ROOM_1', 'direction' => 'LEFT'],
            ['from_node' => 'NODE_0', 'to_node' => 'NODE_1', 'direction' => 'STRAIGHT'],
            ['from_node' => 'NODE_1', 'to_node' => 'NODE_2', 'direction' => 'LEFT'],
            ['from_node' => 'NODE_1', 'to_node' => 'ROOM_4', 'direction' => 'RIGHT'],
            ['from_node' => 'NODE_1', 'to_node' => 'ROOM_5', 'direction' => 'STRAIGHT'],
            ['from_node' => 'NODE_2', 'to_node' => 'ROOM_3', 'direction' => 'LEFT'],
            ['from_node' => 'NODE_2', 'to_node' => 'ROOM_2', 'direction' => 'RIGHT'],
        ], $response->json('connections'));

        $this->assertSame([
            'room_id' => Room::query()->where('room_number', '2')->value('id'),
            'room_number' => '2',
            'steps' => [
                ['from_node' => 'ROOM_2', 'to_node' => 'NODE_2', 'direction' => 'U_TURN'],
                ['from_node' => 'NODE_2', 'to_node' => 'NODE_1', 'direction' => 'LEFT'],
                ['from_node' => 'NODE_1', 'to_node' => 'NODE_0', 'direction' => 'RIGHT'],
            ],
        ], $response->json('return_routes.1'));

        $this->assertSame($countsBefore, [
            Room::query()->count(),
            Node::query()->count(),
            Connection::query()->count(),
        ]);
    }

    public function test_marker_ids_are_unique_at_the_database_level(): void
    {
        $this->expectException(QueryException::class);

        Node::query()->create([
            'node_code' => 'DUPLICATE_MARKER',
            'node_type' => 'intersection',
            'marker_id' => 0,
        ]);
    }

    public function test_repeated_seeding_does_not_duplicate_or_replace_map_records(): void
    {
        $roomIds = Room::query()->orderBy('id')->pluck('id')->all();
        $nodeIds = Node::query()->orderBy('id')->pluck('id')->all();
        $connectionIds = Connection::query()->orderBy('id')->pluck('id')->all();

        $this->seed(PhysicalNavigationMapSeeder::class);

        $this->assertSame($roomIds, Room::query()->orderBy('id')->pluck('id')->all());
        $this->assertSame($nodeIds, Node::query()->orderBy('id')->pluck('id')->all());
        $this->assertSame($connectionIds, Connection::query()->orderBy('id')->pluck('id')->all());
        $this->assertCount(7, $this->connectionKeys());
    }

    public function test_seeding_preserves_existing_medicines_and_missions(): void
    {
        $mission = $this->missionForRoom(1);
        $medicineId = $mission->medicine_id;

        $this->seed(PhysicalNavigationMapSeeder::class);

        $this->assertTrue(Mission::query()->whereKey($mission->id)->exists());
        $this->assertTrue(Medicine::query()->whereKey($medicineId)->exists());
    }

    private function missionForRoom(int $roomNumber): Mission
    {
        $medicine = Medicine::query()->create([
            'name' => 'Route test medicine '.$roomNumber.'-'.Medicine::query()->count(),
            'description' => 'Used only to verify the approved navigation map.',
            'stock_quantity' => 10,
        ]);

        return Mission::query()->create([
            'room_id' => Room::query()->where('room_number', (string) $roomNumber)->firstOrFail()->id,
            'medicine_id' => $medicine->id,
            'quantity' => 1,
            'status' => 'pending',
        ]);
    }

    private function connectionKeys(): array
    {
        return Connection::query()
            ->with(['fromNode', 'toNode'])
            ->get()
            ->map(fn (Connection $connection): string => implode('|', [
                $connection->fromNode->node_code,
                $connection->toNode->node_code,
                $connection->direction,
            ]))
            ->sort()
            ->values()
            ->all();
    }
}
