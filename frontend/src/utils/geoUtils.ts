/**
 * Haversine distance between two lat/lng points (returns km).
 */
export function haversineDistance(
  lat1: number,
  lng1: number,
  lat2: number,
  lng2: number,
): number {
  const R = 6371;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLng = ((lng2 - lng1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((lat1 * Math.PI) / 180) *
      Math.cos((lat2 * Math.PI) / 180) *
      Math.sin(dLng / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

/** Check if a point is inside a bounding box [minLat, minLng, maxLat, maxLng] */
export function isInBounds(
  lat: number,
  lng: number,
  bbox: [number, number, number, number],
): boolean {
  const [minLat, minLng, maxLat, maxLng] = bbox;
  return lat >= minLat && lat <= maxLat && lng >= minLng && lng <= maxLng;
}

interface Point {
  lat: number;
  lng: number;
  [key: string]: unknown;
}

/** Naive grid-based clustering of points. Returns cluster centres. */
export function clusterPoints<T extends Point>(
  points: T[],
  gridSizeDeg = 2,
): Array<{ lat: number; lng: number; count: number; items: T[] }> {
  const grid = new Map<string, { lat: number; lng: number; count: number; items: T[] }>();
  for (const p of points) {
    const key = `${Math.floor(p.lat / gridSizeDeg)},${Math.floor(p.lng / gridSizeDeg)}`;
    if (!grid.has(key)) {
      grid.set(key, { lat: p.lat, lng: p.lng, count: 0, items: [] });
    }
    const cell = grid.get(key)!;
    cell.count++;
    cell.items.push(p);
    // Update centroid
    cell.lat = cell.items.reduce((s, i) => s + i.lat, 0) / cell.items.length;
    cell.lng = cell.items.reduce((s, i) => s + i.lng, 0) / cell.items.length;
  }
  return Array.from(grid.values());
}
