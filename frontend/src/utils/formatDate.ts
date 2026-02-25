/**
 * Format an ISO date string in Tehran timezone (Asia/Tehran, UTC+3:30).
 * Backend stores UTC but SQLite strips the timezone — append "Z" if missing.
 */
export function formatDateTime(iso: string): string {
  const utc = iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z";
  return new Date(utc).toLocaleString("en-US", {
    timeZone: "Asia/Tehran",
    hour12: false,
  });
}
