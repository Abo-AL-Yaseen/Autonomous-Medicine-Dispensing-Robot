<?php

return [
    /*
    |--------------------------------------------------------------------------
    | Approved physical return routes
    |--------------------------------------------------------------------------
    |
    | These decisions are heading-aware after the robot turns around inside
    | each room. NODE_0 remains a normal intersection; HOME is the physical
    | return target after the final straight segment from NODE_0.
    |
    */
    'return_routes' => [
        '1' => [
            ['from_node' => 'ROOM_1', 'to_node' => 'NODE_0', 'direction' => 'U_TURN'],
            ['from_node' => 'NODE_0', 'to_node' => 'HOME', 'direction' => 'RIGHT'],
        ],
        '2' => [
            ['from_node' => 'ROOM_2', 'to_node' => 'NODE_2', 'direction' => 'U_TURN'],
            ['from_node' => 'NODE_2', 'to_node' => 'NODE_1', 'direction' => 'LEFT'],
            ['from_node' => 'NODE_1', 'to_node' => 'NODE_0', 'direction' => 'RIGHT'],
            ['from_node' => 'NODE_0', 'to_node' => 'HOME', 'direction' => 'STRAIGHT'],
        ],
        '3' => [
            ['from_node' => 'ROOM_3', 'to_node' => 'NODE_2', 'direction' => 'U_TURN'],
            ['from_node' => 'NODE_2', 'to_node' => 'NODE_1', 'direction' => 'RIGHT'],
            ['from_node' => 'NODE_1', 'to_node' => 'NODE_0', 'direction' => 'RIGHT'],
            ['from_node' => 'NODE_0', 'to_node' => 'HOME', 'direction' => 'STRAIGHT'],
        ],
        '4' => [
            ['from_node' => 'ROOM_4', 'to_node' => 'NODE_1', 'direction' => 'U_TURN'],
            ['from_node' => 'NODE_1', 'to_node' => 'NODE_0', 'direction' => 'LEFT'],
            ['from_node' => 'NODE_0', 'to_node' => 'HOME', 'direction' => 'STRAIGHT'],
        ],
        '5' => [
            ['from_node' => 'ROOM_5', 'to_node' => 'NODE_1', 'direction' => 'U_TURN'],
            ['from_node' => 'NODE_1', 'to_node' => 'NODE_0', 'direction' => 'STRAIGHT'],
            ['from_node' => 'NODE_0', 'to_node' => 'HOME', 'direction' => 'STRAIGHT'],
        ],
    ],
];
