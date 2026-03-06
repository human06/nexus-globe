/** Format a Unix ms timestamp to HH:MM:SS UTC */
export function formatTime(ts: number): string {
  return new Date(ts).toISOString().substring(11, 19) + ' UTC';
}

/** Format lat/lng to a human-readable string */
export function formatCoords(lat: number, lng: number): string {
  const latDir = lat >= 0 ? 'N' : 'S';
  const lngDir = lng >= 0 ? 'E' : 'W';
  return `${Math.abs(lat).toFixed(4)}°${latDir} ${Math.abs(lng).toFixed(4)}°${lngDir}`;
}

/** Format speed in km/h */
export function formatSpeed(kmh: number): string {
  return `${Math.round(kmh)} km/h`;
}

/** Return a human-readable label for severity 1–5 */
export function severityLabel(severity: number): string {
  const labels: Record<number, string> = {
    1: 'Low',
    2: 'Minor',
    3: 'Moderate',
    4: 'High',
    5: 'Critical',
  };
  return labels[severity] ?? 'Unknown';
}
