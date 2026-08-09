<?php

namespace Tests\Feature;

use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;

class MedicineDispenserBoxTest extends TestCase
{
    use RefreshDatabase;

    public function test_valid_dispenser_box_is_stored_and_returned(): void
    {
        $response = $this->postJson('/api/medicines', [
            'name' => 'Paracetamol',
            'description' => 'Box one medicine',
            'stock_quantity' => 20,
            'dispenser_box' => 1,
        ]);

        $response
            ->assertCreated()
            ->assertJsonPath('data.dispenser_box', 1);
        $this->assertDatabaseHas('medicines', [
            'name' => 'Paracetamol',
            'dispenser_box' => 1,
        ]);
    }

    public function test_invalid_dispenser_box_is_rejected(): void
    {
        $response = $this->postJson('/api/medicines', [
            'name' => 'Invalid Box Medicine',
            'description' => null,
            'stock_quantity' => 20,
            'dispenser_box' => 3,
        ]);

        $response
            ->assertUnprocessable()
            ->assertJsonValidationErrors('dispenser_box');
        $this->assertDatabaseMissing('medicines', [
            'name' => 'Invalid Box Medicine',
        ]);
    }

    public function test_one_physical_box_cannot_map_to_two_medicines(): void
    {
        $payload = [
            'description' => null,
            'stock_quantity' => 20,
            'dispenser_box' => 2,
        ];
        $this->postJson('/api/medicines', [
            ...$payload,
            'name' => 'First Medicine',
        ])->assertCreated();

        $this->postJson('/api/medicines', [
            ...$payload,
            'name' => 'Second Medicine',
        ])
            ->assertUnprocessable()
            ->assertJsonValidationErrors('dispenser_box');
    }
}
