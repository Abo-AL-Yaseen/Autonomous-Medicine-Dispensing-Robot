<?php

namespace App\Http\Requests;

use Illuminate\Foundation\Http\FormRequest;

class StartClaimedMissionRequest extends FormRequest
{
    public function authorize(): bool
    {
        return true;
    }

    public function rules(): array
    {
        return [
            'schedule_claimed_at' => [
                'required',
                'date_format:Y-m-d\TH:i:sP',
            ],
        ];
    }
}
