<?php

namespace App\Services\Navigation;

use App\Models\Connection;
use App\Models\Mission;

class PathFindingService
{
    /**
     * Find the next node along the shortest route from a current node to the mission's target room.
     *
     * This implementation is graph-driven and intentionally isolated so it can later be replaced
     * with Dijkstra or A* without changing the API contract.
     */
    public function nextNodeForMission(Mission $mission, string $currentNodeCode): ?string
    {
        $targetRoomNode = $this->resolveTargetRoomNode($mission);

        if (! $targetRoomNode) {
            return null;
        }

        $graph = $this->loadGraph();
        $queue = [[$currentNodeCode]];
        $visited = [$currentNodeCode => true];

        while ($queue) {
            $path = array_shift($queue);
            $nodeCode = $path[count($path) - 1];

            if ($nodeCode === $targetRoomNode) {
                return count($path) > 1 ? $path[1] : $targetRoomNode;
            }

            $adjacent = $graph[$nodeCode] ?? [];

            foreach ($adjacent as $neighbor) {
                if (isset($visited[$neighbor])) {
                    continue;
                }

                $visited[$neighbor] = true;
                $queue[] = [...$path, $neighbor];
            }
        }

        return null;
    }

    /**
     * Resolve the target node for the room associated with the mission.
     */
    public function resolveTargetRoomNode(Mission $mission): ?string
    {
        return $mission->room
            ?->navigationNode
            ?->node_code;
    }

    /**
     * Load the graph into adjacency list form from the database.
     *
     * @return array<string, array<int, string>>
     */
    protected function loadGraph(): array
    {
        $graph = [];

        $connections = Connection::with('fromNode', 'toNode')->get();

        foreach ($connections as $connection) {
            $fromCode = $connection->fromNode?->node_code;
            $toCode = $connection->toNode?->node_code;

            if (! $fromCode || ! $toCode) {
                continue;
            }

            $graph[$fromCode] ??= [];
            $graph[$fromCode][] = $toCode;
        }

        return $graph;
    }
}
