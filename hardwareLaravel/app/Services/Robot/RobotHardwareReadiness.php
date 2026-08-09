<?php

namespace App\Services\Robot;

enum RobotHardwareReadiness
{
    case Ready;
    case HardwareUnavailable;
    case ApiUnavailable;
    case InvalidResponse;
}
