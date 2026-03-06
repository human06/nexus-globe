/**
 * WorldClock — shows the current UTC time, updating every second.
 * pointer-events: none — passes through to globe interaction.
 */
import { useEffect, useState } from 'react';

function getUTC(): string {
  return new Date().toUTCString().slice(17, 25) + ' UTC';
}

export default function WorldClock() {
  const [time, setTime] = useState(getUTC);

  useEffect(() => {
    const id = setInterval(() => setTime(getUTC()), 1_000);
    return () => clearInterval(id);
  }, []);

  return (
    <div
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: '0.75rem',
        color: 'rgba(0, 240, 255, 0.65)',
        letterSpacing: '0.12em',
        lineHeight: 1,
      }}
    >
      {time}
    </div>
  );
}

