import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import {
  DatePicker,
  DateRangePicker,
  TimePicker,
  TimeRangePicker,
  addMonthsToIsoMonth,
  createCalendarMonth,
  dateTimeSelectorStyles,
  formatDateLabel,
  formatDateRangeLabel,
  formatTimeLabel,
  isIsoDate,
  isIsoTime,
  nextDateRangeSelection,
  normalizeTimeRange,
  timeOptions,
} from "../dateTimeSelectors";

describe("date and time selector primitives", () => {
  it("builds a stable calendar month with selection, disabled bounds, and weekday order", () => {
    const month = createCalendarMonth("2026-07", {
      locale: "en",
      maxDate: "2026-07-28",
      minDate: "2026-07-04",
      selectedDate: "2026-07-08",
      weekStartsOn: 1,
    });

    expect(month.monthLabel).toBe("July 2026");
    expect(month.weekdayLabels).toEqual(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]);
    expect(month.weeks).toHaveLength(5);
    expect(month.weeks[0][0]).toMatchObject({
      isoDate: "2026-06-29",
      day: 29,
      inCurrentMonth: false,
      disabled: true,
    });
    expect(month.weeks.flat().find((day) => day.isoDate === "2026-07-08")).toMatchObject({
      selected: true,
      disabled: false,
    });
    expect(month.weeks.flat().find((day) => day.isoDate === "2026-07-29")).toMatchObject({
      disabled: true,
    });
  });

  it("selects date ranges without producing inverted ranges", () => {
    expect(nextDateRangeSelection({ start: null, end: null }, "2026-07-10")).toEqual({
      start: "2026-07-10",
      end: null,
    });
    expect(nextDateRangeSelection({ start: "2026-07-10", end: null }, "2026-07-08")).toEqual({
      start: "2026-07-08",
      end: "2026-07-10",
    });
    expect(nextDateRangeSelection({ start: "2026-07-10", end: null }, "2026-07-12")).toEqual({
      start: "2026-07-10",
      end: "2026-07-12",
    });
    expect(nextDateRangeSelection({ start: "2026-07-10", end: "2026-07-12" }, "2026-07-15")).toEqual({
      start: "2026-07-15",
      end: null,
    });
  });

  it("formats dates, ranges, and times in supported locales", () => {
    expect(formatDateLabel("2026-07-08", "es")).toBe("8 jul 2026");
    expect(formatDateLabel(null, "en")).toBe("Select date");
    expect(formatDateRangeLabel({ start: "2026-07-08", end: "2026-07-10" }, "en")).toBe("Jul 8 - Jul 10, 2026");
    expect(formatDateRangeLabel({ start: "2026-07-08", end: null }, "es")).toBe("Desde 8 jul 2026");
    expect(formatTimeLabel("09:30", "es")).toBe("09:30");
    expect(formatTimeLabel(null, "en")).toBe("Select time");
  });

  it("validates ISO dates and times conservatively", () => {
    expect(isIsoDate("2026-02-28")).toBe(true);
    expect(isIsoDate("2026-02-31")).toBe(false);
    expect(isIsoDate("2026-2-3")).toBe(false);
    expect(isIsoTime("00:00")).toBe(true);
    expect(isIsoTime("23:59")).toBe(true);
    expect(isIsoTime("24:00")).toBe(false);
  });

  it("generates bounded time options and keeps ranges ordered", () => {
    expect(timeOptions({ maxTime: "10:00", minTime: "09:00", minuteStep: 30 })).toEqual([
      { label: "09:00", value: "09:00" },
      { label: "09:30", value: "09:30" },
      { label: "10:00", value: "10:00" },
    ]);
    expect(normalizeTimeRange({ start: "14:00", end: "09:00" })).toEqual({
      start: "09:00",
      end: "14:00",
    });
    expect(addMonthsToIsoMonth("2026-01", -2)).toBe("2025-11");
  });

  it("renders accessible, styled React selectors without requiring app-specific wrappers", () => {
    const dateMarkup = renderToStaticMarkup(
      <DatePicker locale="en" month="2026-07" onChange={() => undefined} value="2026-07-08" />,
    );
    expect(dateMarkup).toContain("aria-label=\"Choose date\"");
    expect(dateMarkup).toContain("data-selected=\"true\"");
    expect(dateMarkup).toContain(dateTimeSelectorStyles.dayButton);

    const rangeMarkup = renderToStaticMarkup(
      <DateRangePicker
        locale="en"
        month="2026-07"
        onChange={() => undefined}
        value={{ start: "2026-07-08", end: "2026-07-10" }}
      />,
    );
    expect(rangeMarkup).toContain("Jul 8 - Jul 10, 2026");
    expect(rangeMarkup).toContain("data-range-middle=\"true\"");

    const timeMarkup = renderToStaticMarkup(
      <TimePicker locale="en" maxTime="10:00" minTime="09:00" onChange={() => undefined} value="09:30" />,
    );
    expect(timeMarkup).toContain("<option value=\"09:30\" selected=\"\">09:30</option>");

    const timeRangeMarkup = renderToStaticMarkup(
      <TimeRangePicker
        locale="en"
        maxTime="18:00"
        minTime="08:00"
        onChange={() => undefined}
        value={{ start: "09:00", end: "17:00" }}
      />,
    );
    expect(timeRangeMarkup).toContain("Start time");
    expect(timeRangeMarkup).toContain("End time");
  });
});
