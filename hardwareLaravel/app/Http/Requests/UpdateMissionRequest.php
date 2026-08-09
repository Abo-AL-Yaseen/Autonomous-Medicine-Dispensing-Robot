<?php

namespace App\Http\Requests;

use Illuminate\Foundation\Http\FormRequest;
use Illuminate\Validation\Rule;

class UpdateMissionRequest extends FormRequest
{
    public function authorize(): bool
    {
        return true;
    }

    public function rules(): array
    {
        return [
            'room_id' => ['sometimes', 'required', 'integer', 'exists:rooms,id'],
            'medicine_id' => ['sometimes', 'required', 'integer', 'exists:medicines,id'],
            'quantity' => ['sometimes', 'required', 'integer', 'min:1'],
            'status' => ['sometimes', 'required', Rule::in(['pending', 'running', 'completed', 'cancelled'])],
            'scheduled_at' => ['sometimes', 'nullable', 'date_format:Y-m-d H:i:s'],
        ];
    }
}
