/**
 * GlobeContext — shares the live Globe.GL instance with child layer components.
 *
 * Usage:
 *   const globe = useGlobe(); // inside a child of <GlobeCanvas>
 */
import { createContext, useContext } from 'react';
import type Globe from 'globe.gl';

// GlobeInstance is the return type of Globe()(domElement)
type GlobeFactory = typeof Globe;
type GlobeInstance = ReturnType<ReturnType<GlobeFactory>>;

export type { GlobeInstance };

export const GlobeContext = createContext<GlobeInstance | null>(null);

export function useGlobe(): GlobeInstance | null {
  return useContext(GlobeContext);
}
