import { Medicine } from "@/src/types";

export type DispenserBox = 1 | 2;

export interface SelectedMedicineItem {
  medicine_id: number;
  quantity: number;
}

export const requiredDispenserBoxes = (
  medicines: Medicine[],
  items: SelectedMedicineItem[],
): DispenserBox[] => {
  const selectedMedicineIds = new Set(
    items.filter((item) => item.quantity > 0).map((item) => item.medicine_id),
  );
  const boxes = medicines.flatMap((medicine) =>
    selectedMedicineIds.has(medicine.id) &&
    (medicine.dispenser_box === 1 || medicine.dispenser_box === 2)
      ? [medicine.dispenser_box]
      : [],
  );
  return [...new Set(boxes)].sort() as DispenserBox[];
};
