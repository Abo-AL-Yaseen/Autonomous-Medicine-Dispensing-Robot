<?php

return [
    /*
    |--------------------------------------------------------------------------
    | Approved physical return routes
    |--------------------------------------------------------------------------
    |
    | These decisions are heading-aware after the robot turns around inside
    | each room. NODE_0 (marker 0) is the physical return target.
    |
    */
    'return_routes' => [
        '1' => [
            ['from_node' => 'ROOM_1', 'to_node' => 'NODE_0', 'direction' => 'U_TURN'],
        ],
        '2' => [
            ['from_node' => 'ROOM_2', 'to_node' => 'NODE_2', 'direction' => 'U_TURN'],
            ['from_node' => 'NODE_2', 'to_node' => 'NODE_1', 'direction' => 'LEFT'],
            ['from_node' => 'NODE_1', 'to_node' => 'NODE_0', 'direction' => 'RIGHT'],
        ],
        '3' => [
            ['from_node' => 'ROOM_3', 'to_node' => 'NODE_2', 'direction' => 'U_TURN'],
            ['from_node' => 'NODE_2', 'to_node' => 'NODE_1', 'direction' => 'RIGHT'],
            ['from_node' => 'NODE_1', 'to_node' => 'NODE_0', 'direction' => 'RIGHT'],
        ],
        '4' => [
            ['from_node' => 'ROOM_4', 'to_node' => 'NODE_1', 'direction' => 'U_TURN'],
            ['from_node' => 'NODE_1', 'to_node' => 'NODE_0', 'direction' => 'LEFT'],
        ],
        '5' => [
            ['from_node' => 'ROOM_5', 'to_node' => 'NODE_1', 'direction' => 'U_TURN'],
            ['from_node' => 'NODE_1', 'to_node' => 'NODE_0', 'direction' => 'STRAIGHT'],
        ],
    ],
];
