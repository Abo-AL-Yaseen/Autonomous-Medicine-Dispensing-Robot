<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\Connection;
use App\Models\Node;
use App\Models\Room;
use Illuminate\Http\JsonResponse;

class PhysicalNavigationMapController extends Controller
{
    /**
     * Return the read-only physical map consumed by the robot controller.
     */
    public function __invoke(): JsonResponse
    {
        $rooms = Room::query()
            ->with('navigationNode')
            ->orderBy('room_number')
            ->get()
            ->map(fn (Room $room): array => [
                'id' => $room->id,
                'room_number' => $room->room_number,
                'room_name' => $room->room_name,
                'destination_node' => $room->navigationNode === null ? null : [
                    'id' => $room->navigationNode->id,
                    'node_name' => $room->navigationNode->node_code,
                    'marker_id' => $room->navigationNode->marker_id,
                ],
            ]);

        $nodes = Node::query()
            ->orderBy('marker_id')
            ->orderBy('id')
            ->get()
            ->map(fn (Node $node): array => [
                'id' => $node->id,
                'node_name' => $node->node_code,
                'node_type' => $node->node_type,
                'marker_id' => $node->marker_id,
            ]);

        $connections = Connection::query()
            ->with(['fromNode', 'toNode'])
            ->orderBy('id')
            ->get()
            ->map(fn (Connection $connection): array => [
                'from_node' => $connection->fromNode->node_code,
                'to_node' => $connection->toNode->node_code,
                'direction' => $connection->direction,
            ]);

        return response()->json([
            'success' => true,
            'rooms' => $rooms,
            'nodes' => $nodes,
            'connections' => $connections,
        ]);
    }
}
