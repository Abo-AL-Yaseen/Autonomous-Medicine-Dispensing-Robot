<?php

namespace App\Http\Requests;

use Illuminate\Foundation\Http\FormRequest;
use Illuminate\Validation\Rule;

class UpdateRobotStatusRequest extends FormRequest
{
    public function authorize(): bool
    {
        return true;
    }

    public function rules(): array
    {
        return [
            'battery' => ['sometimes', 'required', 'integer', 'min:0', 'max:100'],
            'current_node_id' => ['nullable', 'integer', 'exists:nodes,id'],
            'current_mission_id' => ['nullable', 'integer', 'exists:missions,id'],
            'status' => ['sometimes', 'required', Rule::in(['idle', 'moving', 'charging', 'error'])],
            'connected' => ['sometimes', 'required', 'boolean'],
        ];
    }
}
