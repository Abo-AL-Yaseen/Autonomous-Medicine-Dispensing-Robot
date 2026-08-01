<?php

namespace App\Http\Requests;

use Illuminate\Foundation\Http\FormRequest;

class RobotNavigationDecisionRequest extends FormRequest
{
    public function authorize(): bool
    {
        return true;
    }

    public function rules(): array
    {
        return [
            'mission_id' => ['required', 'integer', 'exists:missions,id'],
            'current_node' => ['required', 'string', 'max:255'],
            'available_nodes' => ['required', 'array'],
            'available_nodes.*' => ['required', 'string', 'max:255'],
        ];
    }
}
