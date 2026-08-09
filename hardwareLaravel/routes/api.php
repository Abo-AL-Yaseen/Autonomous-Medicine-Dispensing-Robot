<?php

use App\Http\Controllers\Api\MedicineController;
use App\Http\Controllers\Api\MissionClaimController;
use App\Http\Controllers\Api\MissionController;
use App\Http\Controllers\Api\RobotNavigationController;
use App\Http\Controllers\Api\RobotStatusController;
use App\Http\Controllers\Api\RoomController;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Route;

Route::middleware('api')->group(function () {
    Route::apiResource('rooms', RoomController::class);
    Route::apiResource('medicines', MedicineController::class);

    Route::post('missions/claim-due', MissionClaimController::class);
    Route::get('missions', [MissionController::class, 'index']);
    Route::get('missions/{mission}', [MissionController::class, 'show']);
    Route::post('missions', [MissionController::class, 'store']);
    Route::patch('missions/{mission}', [MissionController::class, 'update']);
    Route::delete('missions/{mission}', [MissionController::class, 'destroy']);

    Route::get('robot/status', [RobotStatusController::class, 'index']);
    Route::patch('robot/status', [RobotStatusController::class, 'update']);

    Route::post('robot/navigation/start', [RobotNavigationController::class, 'start']);
    Route::post('robot/navigation/decision', [RobotNavigationController::class, 'decision']);
    Route::post('robot/navigation/arrived', [RobotNavigationController::class, 'arrived']);
});

Route::get('/user', function (Request $request) {
    return $request->user();
})->middleware('auth:sanctum');
