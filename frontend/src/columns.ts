import type { ColumnSummary } from "./types";

/** pandas 3 reports text columns as "str"; older versions report "object". */
export function isTextColumn(column: ColumnSummary): boolean {
  const dtype = column.dtype.toLowerCase();
  return dtype === "object" || dtype.includes("str") || dtype.includes("category");
}

export function isNumericColumn(column: ColumnSummary): boolean {
  return column.mean !== undefined || column.dtype.includes("int") || column.dtype.includes("float");
}

/** Columns that make sense as a grouping variable. */
export function isCategoricalColumn(column: ColumnSummary): boolean {
  return isTextColumn(column) || column.n_unique <= 15;
}
