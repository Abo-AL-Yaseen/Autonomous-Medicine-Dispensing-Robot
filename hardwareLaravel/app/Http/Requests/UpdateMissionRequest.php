<?php

namespace App\Http\Requests;

use App\Models\Medicine;
use Illuminate\Foundation\Http\FormRequest;
use Illuminate\Validation\Rule;
use Illuminate\Validation\Validator;

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
            'items' => ['sometimes', 'required', 'array', 'min:1'],
            'items.*.medicine_id' => ['required', 'integer', 'distinct', 'exists:medicines,id'],
            'items.*.quantity' => ['required', 'integer', 'min:1'],
            'status' => ['sometimes', 'required', Rule::in(['pending', 'running', 'completed', 'cancelled'])],
            'scheduled_at' => ['sometimes', 'nullable', 'date_format:Y-m-d H:i:s'],
        ];
    }

    public function after(): array
    {
        return [function (Validator $validator): void {
            foreach ($this->input('items', []) as $index => $item) {
                $box = Medicine::query()
                    ->whereKey($item['medicine_id'] ?? null)
                    ->value('dispenser_box');
                if (! in_array($box, [1, 2], true)) {
                    $validator->errors()->add(
                        "items.$index.medicine_id",
                        'The selected medicine must have dispenser box 1 or 2.',
                    );
                }
            }
        }];
    }
}
