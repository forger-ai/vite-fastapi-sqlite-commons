import { useEffect, useId, useMemo, useState } from "react";
import type { Locale } from "./locale";

export type IsoDate = string;
export type IsoMonth = string;
export type IsoTime = string;
export type WeekStartsOn = 0 | 1;

export interface DateRangeValue {
  start: IsoDate | null;
  end: IsoDate | null;
}

export interface TimeRangeValue {
  start: IsoTime | null;
  end: IsoTime | null;
}

export interface CalendarDay {
  isoDate: IsoDate;
  day: number;
  inCurrentMonth: boolean;
  disabled: boolean;
  today: boolean;
  selected: boolean;
  rangeStart: boolean;
  rangeEnd: boolean;
  rangeMiddle: boolean;
}

export interface CalendarMonth {
  isoMonth: IsoMonth;
  monthLabel: string;
  weekdayLabels: string[];
  weeks: CalendarDay[][];
}

export interface CalendarMonthOptions {
  locale?: Locale;
  weekStartsOn?: WeekStartsOn;
  minDate?: IsoDate | null;
  maxDate?: IsoDate | null;
  disabledDates?: IsoDate[];
  selectedDate?: IsoDate | null;
  selectedRange?: DateRangeValue;
  today?: IsoDate;
}

export interface DateTimeSelectorLabels {
  chooseDate: string;
  chooseRange: string;
  clear: string;
  date: string;
  endDate: string;
  endTime: string;
  from: string;
  nextMonth: string;
  previousMonth: string;
  range: string;
  selectDate: string;
  selectRange: string;
  selectTime: string;
  startDate: string;
  startTime: string;
  time: string;
  to: string;
}

type PartialLabels = Partial<DateTimeSelectorLabels>;

interface BaseSelectorProps {
  className?: string;
  labels?: PartialLabels;
  locale?: Locale;
}

export interface DatePickerProps extends BaseSelectorProps {
  value: IsoDate | null;
  onChange?: (value: IsoDate) => void;
  month?: IsoMonth;
  onMonthChange?: (month: IsoMonth) => void;
  minDate?: IsoDate | null;
  maxDate?: IsoDate | null;
  disabledDates?: IsoDate[];
  weekStartsOn?: WeekStartsOn;
}

export interface DateRangePickerProps extends BaseSelectorProps {
  value: DateRangeValue;
  onChange?: (value: DateRangeValue) => void;
  month?: IsoMonth;
  onMonthChange?: (month: IsoMonth) => void;
  minDate?: IsoDate | null;
  maxDate?: IsoDate | null;
  disabledDates?: IsoDate[];
  weekStartsOn?: WeekStartsOn;
}

export interface TimeOption {
  label: string;
  value: IsoTime;
}

export interface TimeOptionsConfig {
  minTime?: IsoTime | null;
  maxTime?: IsoTime | null;
  minuteStep?: number;
  locale?: Locale;
}

export interface TimePickerProps extends BaseSelectorProps, TimeOptionsConfig {
  value: IsoTime | null;
  onChange?: (value: IsoTime | null) => void;
  label?: string;
  id?: string;
  disabled?: boolean;
}

export interface TimeRangePickerProps extends BaseSelectorProps, TimeOptionsConfig {
  value: TimeRangeValue;
  onChange?: (value: TimeRangeValue) => void;
  disabled?: boolean;
}

const isoDatePattern = /^\d{4}-\d{2}-\d{2}$/;
const isoMonthPattern = /^\d{4}-\d{2}$/;
const isoTimePattern = /^\d{2}:\d{2}$/;

const defaultLabelsByLocale: Record<Locale, DateTimeSelectorLabels> = {
  es: {
    chooseDate: "Elegir fecha",
    chooseRange: "Elegir rango",
    clear: "Limpiar",
    date: "Fecha",
    endDate: "Fin",
    endTime: "Hora final",
    from: "Desde",
    nextMonth: "Mes siguiente",
    previousMonth: "Mes anterior",
    range: "Rango",
    selectDate: "Seleccionar fecha",
    selectRange: "Seleccionar rango",
    selectTime: "Seleccionar hora",
    startDate: "Inicio",
    startTime: "Hora inicial",
    time: "Hora",
    to: "Hasta",
  },
  en: {
    chooseDate: "Choose date",
    chooseRange: "Choose range",
    clear: "Clear",
    date: "Date",
    endDate: "End",
    endTime: "End time",
    from: "From",
    nextMonth: "Next month",
    previousMonth: "Previous month",
    range: "Range",
    selectDate: "Select date",
    selectRange: "Select range",
    selectTime: "Select time",
    startDate: "Start",
    startTime: "Start time",
    time: "Time",
    to: "To",
  },
};

export const dateTimeSelectorStyles = {
  root: "w-full rounded-md border border-border bg-card p-3 text-card-foreground shadow-sm",
  summary: "mb-3 flex min-h-10 items-center justify-between gap-3 rounded-md border border-border bg-background px-3 py-2 text-sm",
  summaryValue: "min-w-0 truncate font-medium text-foreground",
  summaryHint: "shrink-0 text-xs text-muted-foreground",
  monthHeader: "mb-3 flex items-center justify-between gap-2",
  monthButton: "inline-flex h-9 w-9 items-center justify-center rounded-md border border-border bg-background text-sm font-medium text-foreground shadow-sm transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50",
  monthLabel: "min-w-0 flex-1 text-center text-sm font-semibold text-foreground",
  weekdayGrid: "grid grid-cols-7 gap-1",
  weekday: "flex h-7 items-center justify-center text-xs font-medium text-muted-foreground",
  dayButton: "inline-flex h-9 w-full min-w-0 items-center justify-center rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-35",
  dayDefault: "text-foreground hover:bg-muted",
  dayOutside: "text-muted-foreground",
  daySelected: "bg-primary text-primary-foreground hover:bg-primary",
  dayRangeMiddle: "bg-accent text-accent-foreground hover:bg-accent",
  dayToday: "ring-1 ring-ring",
  fieldGroup: "grid gap-2",
  fieldLabel: "text-xs font-medium text-muted-foreground",
  select: "h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
  rangeGrid: "grid gap-3 sm:grid-cols-2",
};

export function isIsoDate(value: unknown): value is IsoDate {
  if (typeof value !== "string" || !isoDatePattern.test(value)) {
    return false;
  }
  const parts = parseIsoDateParts(value);
  if (!parts) {
    return false;
  }
  const date = new Date(Date.UTC(parts.year, parts.month - 1, parts.day));
  return (
    date.getUTCFullYear() === parts.year
    && date.getUTCMonth() === parts.month - 1
    && date.getUTCDate() === parts.day
  );
}

export function isIsoMonth(value: unknown): value is IsoMonth {
  if (typeof value !== "string" || !isoMonthPattern.test(value)) {
    return false;
  }
  const [yearText, monthText] = value.split("-");
  const year = Number(yearText);
  const month = Number(monthText);
  return Number.isInteger(year) && Number.isInteger(month) && month >= 1 && month <= 12;
}

export function isIsoTime(value: unknown): value is IsoTime {
  if (typeof value !== "string" || !isoTimePattern.test(value)) {
    return false;
  }
  const [hourText, minuteText] = value.split(":");
  const hour = Number(hourText);
  const minute = Number(minuteText);
  return Number.isInteger(hour) && Number.isInteger(minute) && hour >= 0 && hour <= 23 && minute >= 0 && minute <= 59;
}

export function addMonthsToIsoMonth(month: IsoMonth, offset: number): IsoMonth {
  const parts = parseIsoMonthParts(isIsoMonth(month) ? month : isoMonthFromDate(new Date()));
  const date = new Date(Date.UTC(parts.year, parts.month - 1 + offset, 1));
  return formatIsoMonth(date.getUTCFullYear(), date.getUTCMonth() + 1);
}

export function createCalendarMonth(month: IsoMonth, options: CalendarMonthOptions = {}): CalendarMonth {
  const locale = options.locale ?? "es";
  const weekStartsOn = options.weekStartsOn ?? 1;
  const visibleMonth = isIsoMonth(month) ? month : isoMonthFromDate(new Date());
  const { year, month: monthNumber } = parseIsoMonthParts(visibleMonth);
  const monthStart = new Date(Date.UTC(year, monthNumber - 1, 1));
  const monthEnd = new Date(Date.UTC(year, monthNumber, 0));
  const gridStart = addUtcDays(monthStart, -weekdayOffset(monthStart.getUTCDay(), weekStartsOn));
  const gridEnd = addUtcDays(monthEnd, weekdayOffset(weekStartsOn + 6, monthEnd.getUTCDay()));
  const disabledDates = new Set((options.disabledDates ?? []).filter(isIsoDate));
  const today = isIsoDate(options.today) ? options.today : todayIsoDate();
  const selectedDate = isIsoDate(options.selectedDate) ? options.selectedDate : null;
  const selectedRange = normalizeDateRange(options.selectedRange ?? { start: null, end: null });
  const weeks: CalendarDay[][] = [];
  let cursor = gridStart;

  while (cursor.getTime() <= gridEnd.getTime()) {
    const week: CalendarDay[] = [];
    for (let index = 0; index < 7; index += 1) {
      const isoDate = isoDateFromUtcDate(cursor);
      const inCurrentMonth = cursor.getUTCMonth() === monthNumber - 1;
      const rangeStart = selectedRange.start === isoDate;
      const rangeEnd = selectedRange.end === isoDate;
      const rangeMiddle = Boolean(
        selectedRange.start
        && selectedRange.end
        && isoDate > selectedRange.start
        && isoDate < selectedRange.end,
      );
      week.push({
        isoDate,
        day: cursor.getUTCDate(),
        inCurrentMonth,
        disabled: isDateDisabled(isoDate, options.minDate, options.maxDate, disabledDates),
        today: today === isoDate,
        selected: selectedDate === isoDate || rangeStart || rangeEnd,
        rangeStart,
        rangeEnd,
        rangeMiddle,
      });
      cursor = addUtcDays(cursor, 1);
    }
    weeks.push(week);
  }

  return {
    isoMonth: visibleMonth,
    monthLabel: monthLabel(visibleMonth, locale),
    weekdayLabels: weekdayLabels(locale, weekStartsOn),
    weeks,
  };
}

export function formatDateLabel(value: IsoDate | null | undefined, locale: Locale = "es", labels?: PartialLabels): string {
  if (!isIsoDate(value)) {
    return mergedLabels(locale, labels).selectDate;
  }
  return new Intl.DateTimeFormat(localeCode(locale), {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
    year: "numeric",
  }).format(utcDateFromIso(value));
}

export function formatDateRangeLabel(value: DateRangeValue, locale: Locale = "es", labels?: PartialLabels): string {
  const text = mergedLabels(locale, labels);
  const range = normalizeDateRange(value);
  if (!range.start && !range.end) {
    return text.selectRange;
  }
  if (range.start && !range.end) {
    return `${text.from} ${formatDateLabel(range.start, locale, labels)}`;
  }
  if (!range.start && range.end) {
    return `${text.to} ${formatDateLabel(range.end, locale, labels)}`;
  }
  if (!range.start || !range.end) {
    return text.selectRange;
  }
  return formatClosedDateRange(range.start, range.end, locale);
}

export function nextDateRangeSelection(current: DateRangeValue, selectedDate: IsoDate): DateRangeValue {
  if (!isIsoDate(selectedDate)) {
    return normalizeDateRange(current);
  }
  const range = normalizeDateRange(current);
  if (!range.start || range.end) {
    return { start: selectedDate, end: null };
  }
  if (selectedDate < range.start) {
    return { start: selectedDate, end: range.start };
  }
  return { start: range.start, end: selectedDate };
}

export function normalizeDateRange(value: DateRangeValue): DateRangeValue {
  const start = isIsoDate(value.start) ? value.start : null;
  const end = isIsoDate(value.end) ? value.end : null;
  if (start && end && start > end) {
    return { start: end, end: start };
  }
  return { start, end };
}

export function timeOptions(config: TimeOptionsConfig = {}): TimeOption[] {
  const min = isIsoTime(config.minTime) ? minutesFromTime(config.minTime) : 0;
  const max = isIsoTime(config.maxTime) ? minutesFromTime(config.maxTime) : (23 * 60) + 59;
  const step = normalizeMinuteStep(config.minuteStep);
  if (min > max) {
    return [];
  }
  const options: TimeOption[] = [];
  for (let minutes = min; minutes <= max; minutes += step) {
    const value = timeFromMinutes(minutes);
    options.push({ value, label: formatTimeLabel(value, config.locale ?? "es") });
  }
  return options;
}

export function formatTimeLabel(value: IsoTime | null | undefined, locale: Locale = "es", labels?: PartialLabels): string {
  if (!isIsoTime(value)) {
    return mergedLabels(locale, labels).selectTime;
  }
  return value;
}

export function normalizeTimeRange(value: TimeRangeValue): TimeRangeValue {
  const start = isIsoTime(value.start) ? value.start : null;
  const end = isIsoTime(value.end) ? value.end : null;
  if (start && end && start > end) {
    return { start: end, end: start };
  }
  return { start, end };
}

export function DatePicker({
  className,
  disabledDates,
  labels,
  locale = "es",
  maxDate,
  minDate,
  month,
  onChange,
  onMonthChange,
  value,
  weekStartsOn,
}: DatePickerProps) {
  const text = mergedLabels(locale, labels);
  const selectedDate = isIsoDate(value) ? value : null;
  const [internalMonth, setInternalMonth] = useState(() => month ?? isoMonthFromIsoDate(selectedDate) ?? isoMonthFromDate(new Date()));
  const visibleMonth = month ?? internalMonth;

  useEffect(() => {
    if (!month && selectedDate) {
      const nextMonth = isoMonthFromIsoDate(selectedDate);
      if (nextMonth) {
        setInternalMonth(nextMonth);
      }
    }
  }, [month, selectedDate]);

  const calendar = useMemo(
    () => createCalendarMonth(visibleMonth, {
      disabledDates,
      locale,
      maxDate,
      minDate,
      selectedDate,
      weekStartsOn,
    }),
    [disabledDates, locale, maxDate, minDate, selectedDate, visibleMonth, weekStartsOn],
  );

  const changeMonth = (nextMonth: IsoMonth) => {
    if (!month) {
      setInternalMonth(nextMonth);
    }
    onMonthChange?.(nextMonth);
  };

  return (
    <div className={cx(dateTimeSelectorStyles.root, className)} data-forger-date-picker="">
      <div className={dateTimeSelectorStyles.summary}>
        <span className={dateTimeSelectorStyles.summaryValue}>{formatDateLabel(selectedDate, locale, labels)}</span>
        <span className={dateTimeSelectorStyles.summaryHint}>{text.date}</span>
      </div>
      <CalendarHeader
        calendar={calendar}
        labels={text}
        onNextMonth={() => changeMonth(addMonthsToIsoMonth(calendar.isoMonth, 1))}
        onPreviousMonth={() => changeMonth(addMonthsToIsoMonth(calendar.isoMonth, -1))}
      />
      <CalendarGrid
        ariaLabel={text.chooseDate}
        calendar={calendar}
        labels={text}
        locale={locale}
        onSelect={(date) => onChange?.(date)}
      />
    </div>
  );
}

export function DateRangePicker({
  className,
  disabledDates,
  labels,
  locale = "es",
  maxDate,
  minDate,
  month,
  onChange,
  onMonthChange,
  value,
  weekStartsOn,
}: DateRangePickerProps) {
  const text = mergedLabels(locale, labels);
  const selectedRange = normalizeDateRange(value);
  const [internalMonth, setInternalMonth] = useState(() => month ?? isoMonthFromIsoDate(selectedRange.start) ?? isoMonthFromDate(new Date()));
  const visibleMonth = month ?? internalMonth;

  useEffect(() => {
    if (!month && selectedRange.start) {
      const nextMonth = isoMonthFromIsoDate(selectedRange.start);
      if (nextMonth) {
        setInternalMonth(nextMonth);
      }
    }
  }, [month, selectedRange.start]);

  const calendar = useMemo(
    () => createCalendarMonth(visibleMonth, {
      disabledDates,
      locale,
      maxDate,
      minDate,
      selectedRange,
      weekStartsOn,
    }),
    [disabledDates, locale, maxDate, minDate, selectedRange, visibleMonth, weekStartsOn],
  );

  const changeMonth = (nextMonth: IsoMonth) => {
    if (!month) {
      setInternalMonth(nextMonth);
    }
    onMonthChange?.(nextMonth);
  };

  return (
    <div className={cx(dateTimeSelectorStyles.root, className)} data-forger-date-range-picker="">
      <div className={dateTimeSelectorStyles.summary}>
        <span className={dateTimeSelectorStyles.summaryValue}>{formatDateRangeLabel(selectedRange, locale, labels)}</span>
        <span className={dateTimeSelectorStyles.summaryHint}>{text.range}</span>
      </div>
      <CalendarHeader
        calendar={calendar}
        labels={text}
        onNextMonth={() => changeMonth(addMonthsToIsoMonth(calendar.isoMonth, 1))}
        onPreviousMonth={() => changeMonth(addMonthsToIsoMonth(calendar.isoMonth, -1))}
      />
      <CalendarGrid
        ariaLabel={text.chooseRange}
        calendar={calendar}
        labels={text}
        locale={locale}
        onSelect={(date) => onChange?.(nextDateRangeSelection(selectedRange, date))}
      />
    </div>
  );
}

export function TimePicker({
  className,
  disabled,
  id,
  label,
  labels,
  locale = "es",
  maxTime,
  minTime,
  minuteStep,
  onChange,
  value,
}: TimePickerProps) {
  const reactId = useId();
  const fieldId = id ?? reactId;
  const text = mergedLabels(locale, labels);
  const currentValue = isIsoTime(value) ? value : "";
  const options = useMemo(
    () => ensureCurrentTimeOption(timeOptions({ locale, maxTime, minTime, minuteStep }), currentValue || null, locale),
    [currentValue, locale, maxTime, minTime, minuteStep],
  );

  return (
    <div className={cx(dateTimeSelectorStyles.fieldGroup, className)} data-forger-time-picker="">
      <label className={dateTimeSelectorStyles.fieldLabel} htmlFor={fieldId}>
        {label ?? text.time}
      </label>
      <select
        className={dateTimeSelectorStyles.select}
        disabled={disabled}
        id={fieldId}
        onChange={(event) => onChange?.(event.currentTarget.value ? event.currentTarget.value : null)}
        value={currentValue}
      >
        <option value="">{text.selectTime}</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}

export function TimeRangePicker({
  className,
  disabled,
  labels,
  locale = "es",
  maxTime,
  minTime,
  minuteStep,
  onChange,
  value,
}: TimeRangePickerProps) {
  const text = mergedLabels(locale, labels);
  const range = normalizeTimeRange(value);

  return (
    <div className={cx(dateTimeSelectorStyles.rangeGrid, className)} data-forger-time-range-picker="">
      <TimePicker
        disabled={disabled}
        label={text.startTime}
        labels={labels}
        locale={locale}
        maxTime={maxTime}
        minTime={minTime}
        minuteStep={minuteStep}
        onChange={(start) => onChange?.(normalizeTimeRange({ ...range, start }))}
        value={range.start}
      />
      <TimePicker
        disabled={disabled}
        label={text.endTime}
        labels={labels}
        locale={locale}
        maxTime={maxTime}
        minTime={minTime}
        minuteStep={minuteStep}
        onChange={(end) => onChange?.(normalizeTimeRange({ ...range, end }))}
        value={range.end}
      />
    </div>
  );
}

function CalendarHeader({
  calendar,
  labels,
  onNextMonth,
  onPreviousMonth,
}: {
  calendar: CalendarMonth;
  labels: DateTimeSelectorLabels;
  onNextMonth: () => void;
  onPreviousMonth: () => void;
}) {
  return (
    <div className={dateTimeSelectorStyles.monthHeader}>
      <button
        aria-label={labels.previousMonth}
        className={dateTimeSelectorStyles.monthButton}
        onClick={onPreviousMonth}
        type="button"
      >
        <span aria-hidden="true">{"<"}</span>
      </button>
      <div className={dateTimeSelectorStyles.monthLabel}>{calendar.monthLabel}</div>
      <button
        aria-label={labels.nextMonth}
        className={dateTimeSelectorStyles.monthButton}
        onClick={onNextMonth}
        type="button"
      >
        <span aria-hidden="true">{">"}</span>
      </button>
    </div>
  );
}

function CalendarGrid({
  ariaLabel,
  calendar,
  labels,
  locale,
  onSelect,
}: {
  ariaLabel: string;
  calendar: CalendarMonth;
  labels: DateTimeSelectorLabels;
  locale: Locale;
  onSelect: (date: IsoDate) => void;
}) {
  return (
    <div aria-label={ariaLabel} role="grid">
      <div className={dateTimeSelectorStyles.weekdayGrid} role="row">
        {calendar.weekdayLabels.map((weekday) => (
          <div className={dateTimeSelectorStyles.weekday} key={weekday} role="columnheader">
            {weekday}
          </div>
        ))}
      </div>
      <div className="mt-1 grid gap-1" role="rowgroup">
        {calendar.weeks.map((week) => (
          <div className={dateTimeSelectorStyles.weekdayGrid} key={week[0]?.isoDate} role="row">
            {week.map((day) => (
              <button
                aria-label={formatDateLabel(day.isoDate, locale, labels)}
                aria-pressed={day.selected}
                className={dayButtonClass(day)}
                data-range-end={day.rangeEnd || undefined}
                data-range-middle={day.rangeMiddle || undefined}
                data-range-start={day.rangeStart || undefined}
                data-selected={day.selected || undefined}
                disabled={day.disabled}
                key={day.isoDate}
                onClick={() => onSelect(day.isoDate)}
                role="gridcell"
                type="button"
              >
                {day.day}
              </button>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

function dayButtonClass(day: CalendarDay): string {
  return cx(
    dateTimeSelectorStyles.dayButton,
    day.selected && dateTimeSelectorStyles.daySelected,
    day.rangeMiddle && dateTimeSelectorStyles.dayRangeMiddle,
    !day.selected && !day.rangeMiddle && dateTimeSelectorStyles.dayDefault,
    !day.inCurrentMonth && dateTimeSelectorStyles.dayOutside,
    day.today && dateTimeSelectorStyles.dayToday,
  );
}

function mergedLabels(locale: Locale, overrides?: PartialLabels): DateTimeSelectorLabels {
  return { ...defaultLabelsByLocale[locale], ...overrides };
}

function parseIsoDateParts(value: string): { year: number; month: number; day: number } | null {
  if (!isoDatePattern.test(value)) {
    return null;
  }
  const [yearText, monthText, dayText] = value.split("-");
  return {
    year: Number(yearText),
    month: Number(monthText),
    day: Number(dayText),
  };
}

function parseIsoMonthParts(value: IsoMonth): { year: number; month: number } {
  const [yearText, monthText] = value.split("-");
  return {
    year: Number(yearText),
    month: Number(monthText),
  };
}

function isDateDisabled(
  isoDate: IsoDate,
  minDate: IsoDate | null | undefined,
  maxDate: IsoDate | null | undefined,
  disabledDates: Set<IsoDate>,
): boolean {
  return (
    disabledDates.has(isoDate)
    || (isIsoDate(minDate) && isoDate < minDate)
    || (isIsoDate(maxDate) && isoDate > maxDate)
  );
}

function localeCode(locale: Locale): string {
  return locale === "en" ? "en-US" : "es-CL";
}

function monthLabel(month: IsoMonth, locale: Locale): string {
  const parts = parseIsoMonthParts(month);
  return new Intl.DateTimeFormat(localeCode(locale), {
    month: "long",
    timeZone: "UTC",
    year: "numeric",
  }).format(new Date(Date.UTC(parts.year, parts.month - 1, 1)));
}

function weekdayLabels(locale: Locale, weekStartsOn: WeekStartsOn): string[] {
  const labels: string[] = [];
  const baseSunday = new Date(Date.UTC(2026, 0, 4));
  for (let offset = 0; offset < 7; offset += 1) {
    const day = (weekStartsOn + offset) % 7;
    labels.push(new Intl.DateTimeFormat(localeCode(locale), {
      timeZone: "UTC",
      weekday: "short",
    }).format(addUtcDays(baseSunday, day)));
  }
  return labels;
}

function formatClosedDateRange(start: IsoDate, end: IsoDate, locale: Locale): string {
  const startDate = utcDateFromIso(start);
  const endDate = utcDateFromIso(end);
  const sameYear = startDate.getUTCFullYear() === endDate.getUTCFullYear();
  const shortFormatter = new Intl.DateTimeFormat(localeCode(locale), {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
  if (sameYear) {
    return `${shortFormatter.format(startDate)} - ${shortFormatter.format(endDate)}, ${endDate.getUTCFullYear()}`;
  }
  return `${formatDateLabel(start, locale)} - ${formatDateLabel(end, locale)}`;
}

function utcDateFromIso(value: IsoDate): Date {
  const parts = parseIsoDateParts(value);
  if (!parts) {
    return new Date(Date.UTC(1970, 0, 1));
  }
  return new Date(Date.UTC(parts.year, parts.month - 1, parts.day));
}

function addUtcDays(value: Date, days: number): Date {
  const next = new Date(value);
  next.setUTCDate(next.getUTCDate() + days);
  return next;
}

function weekdayOffset(day: number, weekStartsOn: number): number {
  return (day - weekStartsOn + 7) % 7;
}

function isoDateFromUtcDate(value: Date): IsoDate {
  return formatIsoDate(value.getUTCFullYear(), value.getUTCMonth() + 1, value.getUTCDate());
}

function isoMonthFromDate(value: Date): IsoMonth {
  return formatIsoMonth(value.getFullYear(), value.getMonth() + 1);
}

function isoMonthFromIsoDate(value: IsoDate | null): IsoMonth | null {
  if (!isIsoDate(value)) {
    return null;
  }
  return value.slice(0, 7);
}

function todayIsoDate(): IsoDate {
  const today = new Date();
  return formatIsoDate(today.getFullYear(), today.getMonth() + 1, today.getDate());
}

function formatIsoDate(year: number, month: number, day: number): IsoDate {
  return `${year.toString().padStart(4, "0")}-${month.toString().padStart(2, "0")}-${day.toString().padStart(2, "0")}`;
}

function formatIsoMonth(year: number, month: number): IsoMonth {
  return `${year.toString().padStart(4, "0")}-${month.toString().padStart(2, "0")}`;
}

function minutesFromTime(value: IsoTime): number {
  const [hourText, minuteText] = value.split(":");
  return (Number(hourText) * 60) + Number(minuteText);
}

function timeFromMinutes(value: number): IsoTime {
  const normalized = Math.max(0, Math.min(value, (23 * 60) + 59));
  return `${Math.floor(normalized / 60).toString().padStart(2, "0")}:${(normalized % 60).toString().padStart(2, "0")}`;
}

function normalizeMinuteStep(value: number | undefined): number {
  if (!Number.isFinite(value) || !value) {
    return 15;
  }
  return Math.max(1, Math.min(60, Math.floor(value)));
}

function ensureCurrentTimeOption(options: TimeOption[], value: IsoTime | null, locale: Locale): TimeOption[] {
  if (!isIsoTime(value) || options.some((option) => option.value === value)) {
    return options;
  }
  return [...options, { label: formatTimeLabel(value, locale), value }].sort((a, b) => a.value.localeCompare(b.value));
}

function cx(...classes: Array<string | false | null | undefined>): string {
  return classes.filter(Boolean).join(" ");
}
