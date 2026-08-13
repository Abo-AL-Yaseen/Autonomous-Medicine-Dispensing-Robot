<?php

namespace Database\Seeders;

use App\Models\User;
use App\Models\Medicine;
use Illuminate\Database\Console\Seeds\WithoutModelEvents;
use Illuminate\Database\Seeder;

class DatabaseSeeder extends Seeder
{
    use WithoutModelEvents;

    /**
     * Seed the application's database.
     */
    public function run(): void
    {
        User::query()->firstOrCreate(
            ['email' => 'test@example.com'],
            ['name' => 'Test User', 'password' => bcrypt('password')],
        );

        Medicine::query()->updateOrCreate(
            ['name' => 'Paracetamol'],
            [
                'description' => 'Box 1 test medicine',
                'stock_quantity' => 20,
                'dispenser_box' => 1,
            ],
        );

        Medicine::query()->updateOrCreate(
            ['name' => 'Ibuprofen'],
            [
                'description' => 'Box 2 test medicine',
                'stock_quantity' => 20,
                'dispenser_box' => 2,
            ],
        );

        $this->call(PhysicalNavigationMapSeeder::class);
    }
}
