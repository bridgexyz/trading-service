/**
 * Format a number with comma separators.
 * Numbers >= 1000 show no decimal places (truncated, not rounded).
 */
export function fmtDollar(value: number, decimals = 2): string {
  const d = Math.abs(value) >= 1000 ? 0 : decimals;
  const truncated = d === 0 ? Math.trunc(value) : value;
  return truncated.toLocaleString("en-US", {
    minimumFractionDigits: d,
    maximumFractionDigits: d,
  });
}

/** Format a price, adaptive decimals for small values. No decimals >= 1000. */
export function fmtPrice(value: number): string {
  if (value < 0.01) return value.toFixed(6);
  if (value >= 1000) {
    return Math.trunc(value).toLocaleString("en-US");
  }
  return value.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/** Format an asset size, adaptive decimals. No decimals >= 1000. */
export function fmtSize(value: number): string {
  if (value < 1) return value.toFixed(6);
  if (value >= 1000) {
    return Math.trunc(value).toLocaleString("en-US");
  }
  return value.toLocaleString("en-US", {
    minimumFractionDigits: 4,
    maximumFractionDigits: 4,
  });
}
