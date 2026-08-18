<?php

namespace App\Http\Requests;

use App\Models\Medicine;
use Illuminate\Foundation\Http\FormRequest;
use Illuminate\Validation\Rule;
use Illuminate\Validation\Validator;

class StoreMissionRequest extends FormRequest
{
    public function authorize(): bool
    {
        return true;
    }

    public function rules(): array
    {
        return [
            'room_id' => ['required', 'integer', 'exists:rooms,id'],
            // Legacy single-item fields remain accepted while mobile clients
            // move to items[].  The controller normalizes both into rows.
            'medicine_id' => ['required_without:items', 'integer', 'exists:medicines,id'],
            'quantity' => ['required_without:items', 'integer', 'min:1'],
            'items' => ['required_without:medicine_id', 'array', 'min:1'],
            'items.*.medicine_id' => ['required', 'integer', 'distinct', 'exists:medicines,id'],
            'items.*.quantity' => ['required', 'integer', 'min:1'],
            'status' => ['nullable', Rule::in(['pending', 'running', 'completed', 'cancelled'])],
            'scheduled_at' => ['nullable', 'date_format:Y-m-d H:i:s'],
        ];
    }

    public function after(): array
    {
        return [function (Validator $validator): void {
            $items = $this->input('items');
            if (! is_array($items) && $this->filled('medicine_id')) {
                $items = [[
                    'medicine_id' => $this->input('medicine_id'),
                ]];
            }
            foreach ($items ?? [] as $index => $item) {
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
