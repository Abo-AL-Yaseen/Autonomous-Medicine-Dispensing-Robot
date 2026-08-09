<?php

namespace App\Http\Requests;

use Illuminate\Foundation\Http\FormRequest;
use Illuminate\Validation\Rule;

class UpdateMedicineRequest extends FormRequest
{
    public function authorize(): bool
    {
        return true;
    }

    public function rules(): array
    {
        return [
            'name' => ['sometimes', 'required', 'string', 'max:255'],
            'description' => ['nullable', 'string'],
            'stock_quantity' => ['sometimes', 'required', 'integer', 'min:0'],
            'dispenser_box' => [
                'sometimes',
                'required',
                'integer',
                Rule::in([1, 2]),
                Rule::unique('medicines', 'dispenser_box')->ignore($this->route('medicine')),
            ],
        ];
    }
}
