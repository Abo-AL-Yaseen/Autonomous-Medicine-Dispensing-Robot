<?php

namespace App\Http\Requests;

use App\Services\Mission\MissionScheduleTime;
use Illuminate\Foundation\Http\FormRequest;
use Illuminate\Validation\Rule;

class ClaimDueMissionRequest extends FormRequest
{
    public function authorize(): bool
    {
        return true;
    }

    public function rules(): array
    {
        return [
            'robot_datetime' => [
                'required',
                'date_format:'.MissionScheduleTime::WALL_CLOCK_FORMAT,
            ],
            'timezone' => [
                'required',
                'string',
                Rule::in([(string) config('services.robot_api.timezone')]),
            ],
        ];
    }
}
