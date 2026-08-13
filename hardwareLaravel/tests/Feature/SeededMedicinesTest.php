<?php

namespace Tests\Feature;

use Database\Seeders\DatabaseSeeder;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;

class SeededMedicinesTest extends TestCase
{
    use RefreshDatabase;

    public function test_seeded_medicines_are_returned_with_their_physical_box_mapping(): void
    {
        $this->seed(DatabaseSeeder::class);

        $response = $this->getJson('/api/medicines');

        $response
            ->assertOk()
            ->assertJsonFragment([
                'name' => 'Paracetamol',
                'stock_quantity' => 20,
                'dispenser_box' => 1,
            ])
            ->assertJsonFragment([
                'name' => 'Ibuprofen',
                'stock_quantity' => 20,
                'dispenser_box' => 2,
            ]);
    }
}
