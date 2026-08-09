export type PickerWallClockSelection = Readonly<{
  value: Date;
  utcOffsetMinutes: number;
}>;

type WallClockParts = Readonly<{
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
}>;

const twoDigits = (value: number): string => String(value).padStart(2, "0");

const assertValidDate = (value: Date): void => {
  if (Number.isNaN(value.getTime())) {
    throw new Error("The scheduled date or time is invalid.");
  }
};

export const createPickerWallClockSelection = (
  value: Date,
  utcOffsetMinutes: number,
): PickerWallClockSelection => {
  assertValidDate(value);
  if (!Number.isFinite(utcOffsetMinutes)) {
    throw new Error("The date picker returned an invalid timezone offset.");
  }

  return { value, utcOffsetMinutes };
};

/**
 * Preserve the fields shown by the native picker. Android returns an instant
 * plus the offset used by its dialog; applying another IANA conversion here
 * can shift the selected wall-clock time when native and JS tzdata differ.
 */
const getPickerWallClockParts = (
  selection: PickerWallClockSelection,
): WallClockParts => {
  const shifted = new Date(
    selection.value.getTime() + selection.utcOffsetMinutes * 60_000,
  );

  return {
    year: shifted.getUTCFullYear(),
    month: shifted.getUTCMonth() + 1,
    day: shifted.getUTCDate(),
    hour: shifted.getUTCHours(),
    minute: shifted.getUTCMinutes(),
  };
};

const getWallClockPartsInTimezone = (
  instant: Date,
  timeZone: string,
): WallClockParts => {
  assertValidDate(instant);
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(instant);
  const values = Object.fromEntries(
    parts.map(({ type, value }) => [type, value]),
  );

  return {
    year: Number(values.year),
    month: Number(values.month),
    day: Number(values.day),
    hour: Number(values.hour),
    minute: Number(values.minute),
  };
};

const formatDateParts = ({ year, month, day }: WallClockParts): string =>
  `${year}-${twoDigits(month)}-${twoDigits(day)}`;

const formatTimeParts = ({ hour, minute }: WallClockParts): string =>
  `${twoDigits(hour)}:${twoDigits(minute)}`;

const wallClockAsUtcDate = (parts: WallClockParts): Date =>
  new Date(
    Date.UTC(
      parts.year,
      parts.month - 1,
      parts.day,
      parts.hour,
      parts.minute,
    ),
  );

export const formatScheduleDateValue = (
  selection: PickerWallClockSelection,
): string => formatDateParts(getPickerWallClockParts(selection));

export const formatScheduleTimeValue = (
  selection: PickerWallClockSelection,
): string => formatTimeParts(getPickerWallClockParts(selection));

export const formatFriendlyScheduleDate = (
  selection: PickerWallClockSelection,
): string =>
  new Intl.DateTimeFormat("en-US", {
    timeZone: "UTC",
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(wallClockAsUtcDate(getPickerWallClockParts(selection)));

export const formatFriendlyScheduleTime = (
  selection: PickerWallClockSelection,
  locale?: string,
): string =>
  new Intl.DateTimeFormat(locale, {
    timeZone: "UTC",
    hour: "numeric",
    minute: "2-digit",
  }).format(wallClockAsUtcDate(getPickerWallClockParts(selection)));

export const formatApiScheduleSummary = (
  utcTimestamp: string,
  timeZone: string,
  locale?: string,
): string => {
  const instant = new Date(utcTimestamp);
  assertValidDate(instant);

  const date = new Intl.DateTimeFormat("en-US", {
    timeZone,
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(instant);
  const time = new Intl.DateTimeFormat(locale, {
    timeZone,
    hour: "numeric",
    minute: "2-digit",
  }).format(instant);

  return `${date} • ${time}`;
};

export const isRobotScheduleInPast = (
  scheduledDate: PickerWallClockSelection,
  scheduledTime: PickerWallClockSelection,
  timeZone: string,
  now = new Date(),
): boolean => {
  const selectedMinute = `${formatScheduleDateValue(
    scheduledDate,
  )} ${formatScheduleTimeValue(scheduledTime)}`;
  const currentParts = getWallClockPartsInTimezone(now, timeZone);
  const currentMinute = `${formatDateParts(currentParts)} ${formatTimeParts(
    currentParts,
  )}`;

  return selectedMinute <= currentMinute;
};
