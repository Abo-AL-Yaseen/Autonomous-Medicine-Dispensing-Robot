<?php

namespace App\Http\Requests;

use Illuminate\Foundation\Http\FormRequest;

class RobotNavigationArrivedRequest extends FormRequest
{
    public function authorize(): bool
    {
        return true;
    }

    public function rules(): array
    {
        return [
            'mission_id' => ['required', 'integer', 'exists:missions,id'],
        ];
    }
}
