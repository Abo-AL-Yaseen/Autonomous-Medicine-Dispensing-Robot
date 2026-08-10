<?php

namespace App\Services\Navigation;

use App\Models\Connection;
use App\Models\Mission;
use App\Models\Node;

class NavigationService
{
    public function __construct(
        protected PathFindingService $pathFindingService,
    ) {}

    public function startMission(Mission $mission): bool
    {
        $mission->status = 'in_progress';

        return $mission->save();
    }

    public function completeMission(Mission $mission): bool
    {
        $mission->status = 'completed';

        return $mission->save();
    }

    public function decideAtIntersection(Mission $mission, string $currentNodeCode, array $availableNodes): array
    {
        $targetNode = $this->pathFindingService->resolveTargetRoomNode($mission);

        if (! $targetNode) {
            return [
                'direction' => 'STOP',
                'next_node' => null,
            ];
        }

        $nextNode = $this->pathFindingService->nextNodeForMission($mission, $currentNodeCode);

        if (! $nextNode || ! in_array($nextNode, $availableNodes, true)) {
            $nextNode = $this->selectAvailableNodeByDirection($mission, $currentNodeCode, $availableNodes);
        }

        $direction = $this->determineDirection($currentNodeCode, $nextNode);

        return [
            'direction' => $direction,
            'next_node' => $nextNode,
        ];
    }

    protected function selectAvailableNodeByDirection(Mission $mission, string $currentNodeCode, array $availableNodes): ?string
    {
        $graph = $this->loadGraph();
        $targetNode = $this->pathFindingService->resolveTargetRoomNode($mission);

        if (! $targetNode) {
            return null;
        }

        $bestNode = null;
        $bestDistance = PHP_INT_MAX;

        foreach ($availableNodes as $nodeCode) {
            $distance = $this->distanceFromNode($graph, $nodeCode, $targetNode);

            if ($distance !== null && $distance < $bestDistance) {
                $bestDistance = $distance;
                $bestNode = $nodeCode;
            }
        }

        return $bestNode;
    }

    protected function determineDirection(string $currentNodeCode, ?string $nextNode): string
    {
        if (! $nextNode) {
            return 'STOP';
        }

        $currentNode = Node::query()->where('node_code', $currentNodeCode)->first();
        $nextNodeModel = Node::query()->where('node_code', $nextNode)->first();

        if (! $currentNode || ! $nextNodeModel) {
            return 'STOP';
        }

        $connection = Connection::query()
            ->where('from_node_id', $currentNode->id)
            ->where('to_node_id', $nextNodeModel->id)
            ->first();

        if ($connection) {
            return $connection->direction;
        }

        return 'STOP';
    }

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

    protected function distanceFromNode(array $graph, string $startNode, string $targetNode): ?int
    {
        $queue = [[$startNode, 0]];
        $visited = [$startNode => true];

        while ($queue) {
            [$node, $distance] = array_shift($queue);

            if ($node === $targetNode) {
                return $distance;
            }

            foreach ($graph[$node] ?? [] as $neighbor) {
                if (isset($visited[$neighbor])) {
                    continue;
                }

                $visited[$neighbor] = true;
                $queue[] = [$neighbor, $distance + 1];
            }
        }

        return null;
    }
}
