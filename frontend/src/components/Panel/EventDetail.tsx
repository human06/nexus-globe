/**
 * EventDetail — shows metadata for the currently selected event.
 * Handles flight events (Epic 1) and news/disaster/ship events (Epic 2).
 */
import { formatCoords, formatSpeed, formatTime } from '../../utils/formatters';
import type { GlobeEvent } from '../../types/events';

const TYPE_COLORS: Record<string, string> = {
  flight:    '#ffee00',
  news:      '#00f0ff',
  ship:      '#00ff88',
  satellite: '#ff00aa',
  disaster:  '#ff6600',
  conflict:  '#ff0044',
  traffic:   '#aa44ff',
  camera:    '#888888',
};

const TYPE_LABELS: Record<string, string> = {
  flight:    'FLIGHT',
  news:      'NEWS',
  ship:      'VESSEL',
  satellite: 'SAT',
  disaster:  'DISASTER',
  conflict:  'CONFLICT',
  traffic:   'TRAFFIC',
  camera:    'CAMERA',
};

interface RowProps { label: string; value: string; dim?: boolean }
function Row({ label, value, dim }: RowProps) {
  return (
    <div style={{ display: 'flex', gap: 8, fontSize: '0.78rem', lineHeight: '1.7', opacity: dim ? 0.55 : 1 }}>
      <span style={{ color: 'rgba(0, 240, 255, 0.4)', minWidth: 80, flexShrink: 0, fontFamily: 'var(--font-mono)' }}>
        {label}
      </span>
      <span style={{ color: '#e0f4ff', fontFamily: 'var(--font-mono)', wordBreak: 'break-all' }}>
        {value}
      </span>
    </div>
  );
}

// ── Severity badge ───────────────────────────────────────────────────────────

const SEV_LABELS: Record<number, string> = {
  1: 'LOW', 2: 'MINOR', 3: 'MODERATE', 4: 'HIGH', 5: 'CRITICAL',
};
const SEV_COLORS: Record<number, string> = {
  1: '#44ff88', 2: '#aaff44', 3: '#ffcc00', 4: '#ff6600', 5: '#ff2244',
};

function SevBadge({ sev }: { sev: number }) {
  const color = SEV_COLORS[sev] ?? '#888';
  return (
    <span style={{
      fontFamily: 'var(--font-display)',
      fontSize: '0.58rem',
      letterSpacing: '0.12em',
      color,
      background: `${color}18`,
      border: `1px solid ${color}55`,
      borderRadius: 2,
      padding: '2px 5px',
    }}>
      {SEV_LABELS[sev] ?? `SEV ${sev}`}
    </span>
  );
}

// ── News-specific detail panel ───────────────────────────────────────────────

function NewsDetail({ event }: { event: GlobeEvent }) {
  const meta = event.metadata as Record<string, unknown>;

  const aiSummary   = typeof meta.ai_summary   === 'string' ? meta.ai_summary   : null;
  const aiCategory  = typeof meta.ai_category  === 'string' ? meta.ai_category  : null;
  const aiEntities  = Array.isArray(meta.ai_entities)        ? (meta.ai_entities as string[]) : [];
  const aiTags      = Array.isArray(meta.ai_tags)            ? (meta.ai_tags     as string[]) : [];
  const confirmedBy = Array.isArray(meta.confirmed_by)       ? (meta.confirmed_by as string[]) : [];
  const confirmCnt  = Number(meta.confirmation_count ?? 1);
  const isAiGeocoded    = Boolean(meta.ai_geocoded);
  const isAiEnriched    = Boolean(meta.ai_enriched);
  const geocodeConf     = typeof meta.geocode_confidence === 'number' ? meta.geocode_confidence : null;
  const locationName    = typeof meta.location_name === 'string'      ? meta.location_name      : null;
  const firstSeen       = typeof meta.first_seen    === 'string'      ? meta.first_seen          : null;

  const HR = (
    <div style={{ borderBottom: '1px solid rgba(0,240,255,0.08)', margin: '8px 0' }} />
  );

  return (
    <div style={{ marginBottom: 8 }}>

      {/* AI Summary ─────────────────────────────────────────────────────── */}
      {aiSummary && (
        <div style={{
          background: 'rgba(0,240,255,0.05)',
          border: '1px solid rgba(0,240,255,0.15)',
          borderRadius: 3,
          padding: '8px 10px',
          marginBottom: 10,
        }}>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 6, marginBottom: 5,
          }}>
            <span style={{
              fontFamily: 'var(--font-display)',
              fontSize: '0.58rem',
              letterSpacing: '0.15em',
              color: '#00f0ff',
              background: 'rgba(0,240,255,0.12)',
              border: '1px solid rgba(0,240,255,0.3)',
              borderRadius: 2,
              padding: '1px 5px',
            }}>
              AI ANALYZED
            </span>
            {aiCategory && (
              <span style={{
                fontFamily: 'var(--font-display)',
                fontSize: '0.58rem',
                letterSpacing: '0.1em',
                color: 'rgba(0,240,255,0.6)',
              }}>
                {aiCategory.toUpperCase()}
              </span>
            )}
          </div>
          <p style={{
            margin: 0,
            fontFamily: 'var(--font-mono)',
            fontSize: '0.76rem',
            color: '#b0ddf0',
            lineHeight: 1.55,
          }}>
            {aiSummary}
          </p>
        </div>
      )}

      {/* Multi-source confirmation ───────────────────────────────────────── */}
      {confirmCnt > 1 && (
        <div style={{
          background: 'rgba(0,255,136,0.05)',
          border: '1px solid rgba(0,255,136,0.2)',
          borderRadius: 3,
          padding: '6px 10px',
          marginBottom: 8,
          fontFamily: 'var(--font-mono)',
          fontSize: '0.75rem',
        }}>
          <span style={{ color: '#00ff88' }}>✓ Confirmed by {confirmCnt} source{confirmCnt > 1 ? 's' : ''}</span>
          {confirmedBy.length > 0 && (
            <div style={{
              marginTop: 4,
              display: 'flex',
              flexWrap: 'wrap',
              gap: 4,
            }}>
              {confirmedBy.map((src) => (
                <span key={src} style={{
                  fontFamily: 'var(--font-display)',
                  fontSize: '0.58rem',
                  letterSpacing: '0.08em',
                  color: '#00ff88',
                  background: 'rgba(0,255,136,0.1)',
                  border: '1px solid rgba(0,255,136,0.25)',
                  borderRadius: 2,
                  padding: '1px 5px',
                }}>
                  {src}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Severity */}
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 7 }}>
        <SevBadge sev={event.severity} />
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem', color: 'rgba(0,240,255,0.4)' }}>
          {'█'.repeat(event.severity)}{'░'.repeat(5 - event.severity)}
        </span>
      </div>

      {HR}

      {/* Location ───────────────────────────────────────────────────────── */}
      {locationName && <Row label="LOCATION" value={locationName} />}
      <Row label="COORDS"   value={`${event.latitude.toFixed(3)}, ${event.longitude.toFixed(3)}`} />
      {isAiGeocoded && geocodeConf !== null && (
        <Row label="GEO CONF" value={`${(geocodeConf * 100).toFixed(0)}% (AI)`} dim />
      )}

      {HR}

      {/* Source & time ───────────────────────────────────────────────────── */}
      <Row label="SOURCE"    value={event.source} />
      {firstSeen && <Row label="FIRST SEEN" value={new Date(firstSeen).toUTCString().substring(5, 22)} dim />}
      <Row label="TIME"      value={formatTime(event.timestamp)} />
      {event.sourceUrl && (
        <div style={{ marginTop: 6 }}>
          <a
            href={event.sourceUrl}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.72rem',
              color: '#00f0ff',
              textDecoration: 'none',
              borderBottom: '1px solid rgba(0,240,255,0.3)',
              opacity: 0.8,
            }}
          >
            ↗ View source
          </a>
        </div>
      )}

      {/* Entities / Tags ─────────────────────────────────────────────────── */}
      {aiEntities.length > 0 && (
        <>
          {HR}
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.68rem', color: 'rgba(0,240,255,0.4)', marginBottom: 4 }}>
            ENTITIES
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 4 }}>
            {aiEntities.slice(0, 8).map((ent) => (
              <span key={ent} style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '0.68rem',
                color: '#e0f4ff',
                background: 'rgba(0,240,255,0.07)',
                border: '1px solid rgba(0,240,255,0.15)',
                borderRadius: 2,
                padding: '1px 5px',
              }}>
                {ent}
              </span>
            ))}
          </div>
        </>
      )}

      {aiTags.length > 0 && !aiEntities.length && (
        <>
          {HR}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {aiTags.slice(0, 6).map((tag) => (
              <span key={tag} style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '0.67rem',
                color: 'rgba(0,240,255,0.5)',
                background: 'rgba(0,240,255,0.05)',
                border: '1px solid rgba(0,240,255,0.12)',
                borderRadius: 2,
                padding: '1px 5px',
              }}>
                {tag}
              </span>
            ))}
          </div>
        </>
      )}

      {/* Unenriched fallback */}
      {!isAiEnriched && (
        <div style={{
          marginTop: 6,
          fontFamily: 'var(--font-mono)',
          fontSize: '0.68rem',
          color: 'rgba(0,240,255,0.25)',
          fontStyle: 'italic',
        }}>
          AI enrichment pending…
        </div>
      )}
    </div>
  );
}
// ── Disaster detail panel ─────────────────────────────────────────────────────────────

const CAT_COLORS: Record<string, string> = {
  earthquake:        '#ff2244',
  wildfire:          '#ff6600',
  severe_storm:      '#88aaff',
  volcanic_eruption: '#ff2244',
  flood:             '#2244ff',
  landslide:         '#aa8844',
};

const CAT_LABELS: Record<string, string> = {
  earthquake: 'EARTHQUAKE', wildfire: 'WILDFIRE', severe_storm: 'SEVERE STORM',
  volcanic_eruption: 'VOLCANO', flood: 'FLOOD', landslide: 'LANDSLIDE',
};

function DisasterDetail({ event }: { event: GlobeEvent }) {
  const meta      = event.metadata as Record<string, unknown>;
  const catKey    = String(event.category ?? '').toLowerCase();
  const catColor  = CAT_COLORS[catKey] ?? '#ff6600';
  const catLabel  = CAT_LABELS[catKey] ?? event.category.toUpperCase();
  const magnitude = typeof meta.magnitude   === 'number' ? (meta.magnitude as number).toFixed(1) : null;
  const depthKm   = typeof meta.depth_km    === 'number' ? (meta.depth_km as number).toFixed(0)  : null;
  const alertLvl  = typeof meta.alert_level === 'string' ? (meta.alert_level as string) : null;
  const tsunami   = Boolean(meta.tsunami_flag);
  const sourceUrl = typeof meta.usgs_url === 'string' ? (meta.usgs_url as string)
    : typeof meta.eonet_url === 'string' ? (meta.eonet_url as string)
    : event.sourceUrl ?? null;
  const trailLen  = Array.isArray(meta.trail) ? (meta.trail as unknown[]).length : 0;
  const locationName = typeof meta.location_name === 'string' ? (meta.location_name as string) : null;

  const HR = <div style={{ borderBottom: '1px solid rgba(255,80,50,0.12)', margin: '8px 0' }} />;

  return (
    <div style={{ marginBottom: 8 }}>

      {/* Category badge */}
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8, flexWrap: 'wrap' }}>
        <span style={{
          fontFamily: 'var(--font-display)', fontSize: '0.6rem', letterSpacing: '0.15em',
          color: catColor, background: `${catColor}18`, border: `1px solid ${catColor}55`,
          borderRadius: 2, padding: '2px 6px',
        }}>{catLabel}</span>
        <SevBadge sev={event.severity} />
        {tsunami && (
          <span style={{
            fontFamily: 'var(--font-display)', fontSize: '0.6rem', letterSpacing: '0.12em',
            color: '#ffee00', background: 'rgba(255,238,0,0.12)', border: '1px solid rgba(255,238,0,0.4)',
            borderRadius: 2, padding: '2px 6px', animation: 'nexus-pulse 1s ease-in-out infinite',
          }}>⚠ TSUNAMI WATCH</span>
        )}
      </div>

      {/* Alert level bar */}
      {alertLvl && (
        <div style={{
          background: alertLvl === 'red' ? 'rgba(255,0,0,0.12)' : alertLvl === 'orange' ? 'rgba(255,100,0,0.12)' : 'rgba(255,220,0,0.10)',
          border: `1px solid ${alertLvl === 'red' ? 'rgba(255,50,50,0.4)' : alertLvl === 'orange' ? 'rgba(255,120,0,0.4)' : 'rgba(255,220,0,0.3)'}`,
          borderRadius: 3, padding: '5px 10px', marginBottom: 8,
          fontFamily: 'var(--font-display)', fontSize: '0.68rem', letterSpacing: '0.12em',
          color: alertLvl === 'red' ? '#ff6644' : alertLvl === 'orange' ? '#ff9944' : '#ffdd44',
        }}>
          ALERT: {alertLvl.toUpperCase()}
        </div>
      )}

      {HR}

      {/* Magnitude / depth */}
      {magnitude && <Row label="MAGNITUDE" value={`M${magnitude}`} />}
      {depthKm && <Row label="DEPTH" value={`${depthKm} km`} />}
      {locationName && <Row label="LOCATION" value={locationName} />}
      <Row label="COORDS" value={`${event.latitude.toFixed(3)}, ${event.longitude.toFixed(3)}`} />
      {trailLen > 0 && <Row label="TRAIL PTS" value={String(trailLen)} dim />}

      {HR}

      <Row label="SOURCE" value={event.source} />
      <Row label="TIME"   value={formatTime(event.timestamp)} />
      {sourceUrl && (
        <div style={{ marginTop: 6 }}>
          <a href={sourceUrl} target="_blank" rel="noopener noreferrer" style={{
            fontFamily: 'var(--font-mono)', fontSize: '0.72rem', color: catColor,
            textDecoration: 'none', borderBottom: `1px solid ${catColor}44`, opacity: 0.8,
          }}>↗ View data source</a>
        </div>
      )}
    </div>
  );
}

// ── Ship type badge colors ─────────────────────────────────────────────────────
const SHIP_CAT_COLORS: Record<string, string> = {
  cargo:     '#00ff88',
  tanker:    '#00cc66',
  passenger: '#44ffbb',
  fishing:   '#88ffcc',
  special:   '#aaffdd',
};
const SHIP_CAT_LABELS: Record<string, string> = {
  cargo: 'CARGO', tanker: 'TANKER', passenger: 'PASSENGER',
  fishing: 'FISHING', special: 'SPECIAL', ship: 'VESSEL',
};

function ShipDetail({ event }: { event: GlobeEvent }) {
  const meta     = event.metadata as Record<string, unknown>;
  const catKey   = String(event.category ?? '').toLowerCase();
  const catColor = SHIP_CAT_COLORS[catKey] ?? '#00ff88';
  const catLabel = SHIP_CAT_LABELS[catKey] ?? 'VESSEL';
  const sogKts   = typeof meta.sog_kts  === 'number' ? (meta.sog_kts  as number).toFixed(1) + ' kts' : null;
  const cog      = typeof meta.cog      === 'number' ? `${(meta.cog   as number).toFixed(0)}°` : null;
  const hdg      = event.heading != null ? `${Math.round(event.heading)}°` : null;
  const mmsi     = meta.mmsi     ? String(meta.mmsi)     : null;
  const imo      = meta.imo      ? String(meta.imo)      : null;
  const callsign = meta.callsign ? String(meta.callsign) : null;
  const dest     = meta.destination ? String(meta.destination) : null;
  const eta      = meta.eta      ? String(meta.eta)      : null;
  const draught  = typeof meta.draught === 'number' ? `${(meta.draught as number).toFixed(1)} m` : null;
  const length   = typeof meta.length  === 'number' ? `${(meta.length  as number).toFixed(0)} m` : null;
  const width    = typeof meta.width   === 'number' ? `${(meta.width   as number).toFixed(0)} m` : null;
  const flag     = meta.flag_country ? String(meta.flag_country) : null;
  const isAnchor = typeof meta.sog_kts === 'number' && (meta.sog_kts as number) < 0.5;
  const marineUrl = event.sourceUrl
    ?? (mmsi ? `https://www.marinetraffic.com/en/ais/details/ships/mmsi:${mmsi}` : null);

  const HR = <div style={{ borderBottom: '1px solid rgba(0,255,136,0.12)', margin: '8px 0' }} />;

  return (
    <div style={{ marginBottom: 8 }}>

      {/* Category + anchor badge */}
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8, flexWrap: 'wrap' }}>
        <span style={{
          fontFamily: 'var(--font-display)', fontSize: '0.6rem', letterSpacing: '0.15em',
          color: catColor, background: `${catColor}18`, border: `1px solid ${catColor}55`,
          borderRadius: 2, padding: '2px 6px',
        }}>{catLabel}</span>
        {isAnchor && (
          <span style={{
            fontFamily: 'var(--font-display)', fontSize: '0.6rem', letterSpacing: '0.12em',
            color: '#aaaaaa', background: 'rgba(160,160,160,0.12)', border: '1px solid rgba(160,160,160,0.3)',
            borderRadius: 2, padding: '2px 6px',
          }}>⚓ AT ANCHOR</span>
        )}
      </div>

      {HR}

      {mmsi     && <Row label="MMSI"     value={mmsi}     />}
      {imo      && <Row label="IMO"      value={imo}      />}
      {callsign && <Row label="CALLSIGN" value={callsign} />}
      {flag     && <Row label="FLAG"     value={flag}     />}

      {HR}

      {sogKts && <Row label="SPEED"   value={sogKts} />}
      {hdg    && <Row label="HEADING" value={hdg}    />}
      {cog    && <Row label="COG"     value={cog}    />}
      {dest   && <Row label="DEST"    value={dest}   />}
      {eta    && <Row label="ETA"     value={eta}    dim />}

      {(length || draught) && HR}
      {length  && <Row label="LENGTH"  value={length}  />}
      {width   && <Row label="WIDTH"   value={width}   />}
      {draught && <Row label="DRAUGHT" value={draught} />}

      {HR}

      <Row label="POSITION" value={`${event.latitude.toFixed(4)}, ${event.longitude.toFixed(4)}`} />
      <Row label="UPDATED"  value={formatTime(event.timestamp)} />
      <Row label="SOURCE"   value={event.source} dim />

      {marineUrl && (
        <div style={{ marginTop: 6 }}>
          <a href={marineUrl} target="_blank" rel="noopener noreferrer" style={{
            fontFamily: 'var(--font-mono)', fontSize: '0.72rem', color: catColor,
            textDecoration: 'none', borderBottom: `1px solid ${catColor}44`, opacity: 0.8,
          }}>↗ MarineTraffic</a>
        </div>
      )}
    </div>
  );
}

export default function EventDetail({ event }: { event: GlobeEvent }) {
  const meta  = event.metadata as Record<string, unknown>;
  const color = TYPE_COLORS[event.type] ?? '#fff';
  const label = TYPE_LABELS[event.type] ?? event.type.toUpperCase();

  const ktSpeed = event.speed != null ? (event.speed * 0.539957).toFixed(0) + ' kts' : '—';
  const altFt   = event.altitude != null ? (event.altitude * 3.28084).toLocaleString(undefined, { maximumFractionDigits: 0 }) + ' ft' : '—';
  const heading = event.heading != null ? `${Math.round(event.heading)}°` : '—';

  return (
    <div style={{ padding: '0 2px' }}>
      {/* Type badge + title */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <span
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: '0.6rem',
            letterSpacing: '0.15em',
            color,
            background: `${color}18`,
            border: `1px solid ${color}55`,
            borderRadius: 2,
            padding: '2px 6px',
          }}
        >
          {label}
        </span>
      </div>

      <div
        style={{
          fontFamily: 'var(--font-display)',
          fontSize: '0.92rem',
          fontWeight: 700,
          color,
          textShadow: `0 0 8px ${color}`,
          marginBottom: 10,
          letterSpacing: '0.06em',
          lineHeight: 1.2,
        }}
      >
        {event.title}
      </div>

      {/* Flight-specific fields */}
      {event.type === 'flight' && (
        <div style={{ marginBottom: 8, borderBottom: '1px solid rgba(0,240,255,0.08)', paddingBottom: 8 }}>
          {/* Route banner — show only when we have origin or destination */}
          {(meta?.origin || meta?.destination) && (
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 8,
              margin: '6px 0 10px',
              padding: '5px 10px',
              background: 'rgba(0,240,255,0.06)',
              border: '1px solid rgba(0,240,255,0.18)',
              borderRadius: 3,
              fontFamily: 'var(--font-display)',
              fontSize: '0.9rem',
              letterSpacing: '0.15em',
            }}>
              <span style={{ color: '#e0f4ff', opacity: 0.7 }}>{String(meta.origin || '···')}</span>
              <svg width="20" height="10" viewBox="0 0 20 10" fill="none" stroke="var(--neon-cyan)" strokeWidth="1.5">
                <line x1="0" y1="5" x2="16" y2="5" />
                <polyline points="11,1 17,5 11,9" />
              </svg>
              <span style={{ color: '#e0f4ff', opacity: 0.7 }}>{String(meta.destination || '···')}</span>
            </div>
          )}
          <Row label="FLIGHT"   value={String(meta?.number || meta?.callsign || event.title).trim() || '—'} />
          <Row label="CALLSIGN" value={String(meta?.callsign ?? '—').trim() || '—'} />
          <Row label="AIRCRAFT" value={String(meta?.aircraft || '—').trim()} />
          <Row label="REG"      value={String(meta?.registration || '—').trim()} />
          <Row label="ICAO24"   value={String(meta?.icao24 ?? '—').toUpperCase()} />
        </div>
      )}

      {/* News-specific fields */}
      {event.type === 'news' && <NewsDetail event={event} />}

      {/* Disaster-specific fields */}
      {event.type === 'disaster' && <DisasterDetail event={event} />}

      {/* Ship-specific fields */}
      {event.type === 'ship' && <ShipDetail event={event} />}

      {/* Common fields — flight only; news/disaster/ship have their own panels */}
      {event.type !== 'news' && event.type !== 'disaster' && event.type !== 'ship' && (
        <>
          <Row label="ALTITUDE"  value={altFt} />
          <Row label="SPEED"     value={`${formatSpeed(event.speed ?? 0)} · ${ktSpeed}`} />
          <Row label="HEADING"   value={heading} />
          <Row label="POSITION"  value={formatCoords(event.latitude, event.longitude)} />
          <Row label="TIME"      value={formatTime(event.timestamp)} />
          <Row label="SEVERITY"  value={String(event.severity)} />
          <Row label="SOURCE"    value={event.source} dim />
        </>
      )}
    </div>
  );
}

