<?php

namespace Database\Seeders;

use App\Models\Connection;
use App\Models\Node;
use App\Models\Room;
use Illuminate\Database\Seeder;
use Illuminate\Support\Facades\DB;

class PhysicalNavigationMapSeeder extends Seeder
{
    /**
     * Seed the approved physical navigation map without touching missions or medicines.
     */
    public function run(): void
    {
        DB::transaction(function (): void {
            $markerIds = [
                'HOME' => 10,
                'NODE_0' => 0,
                'NODE_1' => 1,
                'NODE_2' => 2,
                'ROOM_1' => 11,
                'ROOM_2' => 12,
                'ROOM_3' => 13,
                'ROOM_4' => 14,
                'ROOM_5' => 15,
            ];

            Node::query()
                ->whereIn('marker_id', array_values($markerIds))
                ->update(['marker_id' => null]);

            $nodes = [];

            foreach ($markerIds as $nodeCode => $markerId) {
                $nodes[$nodeCode] = Node::query()->updateOrCreate(
                    ['node_code' => $nodeCode],
                    [
                        'node_type' => match (true) {
                            $nodeCode === 'HOME' => 'home',
                            str_starts_with($nodeCode, 'ROOM_') => 'room',
                            default => 'intersection',
                        },
                        'marker_id' => $markerId,
                    ],
                );
            }

            foreach (range(1, 5) as $roomNumber) {
                Room::query()->updateOrCreate(
                    ['room_number' => (string) $roomNumber],
                    [
                        'room_name' => 'Room '.$roomNumber,
                        'navigation_node_id' => $nodes['ROOM_'.$roomNumber]->id,
                    ],
                );
            }

            $connections = [
                ['HOME', 'NODE_0', 'STRAIGHT'],
                ['NODE_0', 'HOME', 'STRAIGHT'],
                ['NODE_0', 'ROOM_1', 'LEFT'],
                ['NODE_0', 'NODE_1', 'STRAIGHT'],
                ['NODE_1', 'NODE_2', 'LEFT'],
                ['NODE_1', 'ROOM_4', 'RIGHT'],
                ['NODE_1', 'ROOM_5', 'STRAIGHT'],
                ['NODE_2', 'ROOM_3', 'LEFT'],
                ['NODE_2', 'ROOM_2', 'RIGHT'],
            ];

            $approvedConnectionKeys = collect($connections)
                ->mapWithKeys(fn (array $connection): array => [
                    implode('|', $connection) => true,
                ]);

            Connection::query()
                ->with(['fromNode', 'toNode'])
                ->get()
                ->each(function (Connection $connection) use ($approvedConnectionKeys): void {
                    $key = implode('|', [
                        $connection->fromNode?->node_code,
                        $connection->toNode?->node_code,
                        $connection->direction,
                    ]);

                    if (! $approvedConnectionKeys->has($key)) {
                        $connection->delete();
                    }
                });

            foreach ($connections as [$fromNode, $toNode, $direction]) {
                Connection::query()->updateOrCreate([
                    'from_node_id' => $nodes[$fromNode]->id,
                    'to_node_id' => $nodes[$toNode]->id,
                    'direction' => $direction,
                ]);
            }
        });
    }
}
