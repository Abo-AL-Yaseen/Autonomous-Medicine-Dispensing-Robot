<?php

namespace App\Services\Robot;

use Illuminate\Http\Client\ConnectionException;
use Illuminate\Support\Facades\Http;
use Throwable;

class RobotHardwareApiService
{
    public function checkReadiness(): RobotHardwareReadiness
    {
        $url = rtrim((string) config('services.robot_api.url'), '/').'/health';

        try {
            $response = Http::acceptJson()
                ->connectTimeout((float) config('services.robot_api.connect_timeout'))
                ->timeout((float) config('services.robot_api.timeout'))
                ->get($url);
        } catch (ConnectionException) {
            return RobotHardwareReadiness::ApiUnavailable;
        } catch (Throwable) {
            return RobotHardwareReadiness::ApiUnavailable;
        }

        if (! $response->successful()) {
            return RobotHardwareReadiness::ApiUnavailable;
        }

        $payload = $response->json();

        if (
            ! is_array($payload)
            || ($payload['status'] ?? null) !== 'running'
            || ! array_key_exists('hardware_connected', $payload)
            || ! is_bool($payload['hardware_connected'])
        ) {
            return RobotHardwareReadiness::InvalidResponse;
        }

        return $payload['hardware_connected']
            ? RobotHardwareReadiness::Ready
            : RobotHardwareReadiness::HardwareUnavailable;
    }
}
