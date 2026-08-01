<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Http\Requests\StoreMedicineRequest;
use App\Http\Requests\UpdateMedicineRequest;
use App\Http\Resources\MedicineResource;
use App\Models\Medicine;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Resources\Json\AnonymousResourceCollection;

class MedicineController extends Controller
{
    public function index(): AnonymousResourceCollection
    {
        return MedicineResource::collection(Medicine::query()->latest()->get());
    }

    public function show(Medicine $medicine): MedicineResource
    {
        return new MedicineResource($medicine);
    }

    public function store(StoreMedicineRequest $request): MedicineResource
    {
        $medicine = Medicine::create($request->validated());

        return new MedicineResource($medicine);
    }

    public function update(UpdateMedicineRequest $request, Medicine $medicine): MedicineResource
    {
        $medicine->update($request->validated());

        return new MedicineResource($medicine->fresh());
    }

    public function destroy(Medicine $medicine): JsonResponse
    {
        $medicine->delete();

        return response()->json(null, 204);
    }
}
