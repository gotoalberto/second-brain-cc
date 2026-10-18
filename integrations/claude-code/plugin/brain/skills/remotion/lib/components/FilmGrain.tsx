/**
 * FilmGrain - SVG noise overlay for cinematic texture
 *
 * Adds subtle film grain noise on top of content for a more
 * organic, film-quality look. Uses an SVG feTurbulence filter.
 */

import { useCurrentFrame } from 'remotion';

export interface FilmGrainProps {
  /** Opacity of the grain overlay (0-1). Default: 0.05 */
  opacity?: number;
  /** CSS blend mode. Default: 'overlay' */
  blendMode?: string;
  /** Animate the grain pattern per-frame. Default: true */
  animate?: boolean;
}

export const FilmGrain: React.FC<FilmGrainProps> = ({
  opacity = 0.05,
  blendMode = 'overlay',
  animate = true,
}) => {
  const frame = useCurrentFrame();
  // Shift the seed every frame for animated grain
  const seed = animate ? frame % 100 : 0;

  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        opacity,
        mixBlendMode: blendMode as React.CSSProperties['mixBlendMode'],
        pointerEvents: 'none',
      }}
    >
      <svg width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
        <filter id={`grain-${seed}`}>
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.65"
            numOctaves="3"
            seed={seed}
            stitchTiles="stitch"
          />
        </filter>
        <rect
          width="100%"
          height="100%"
          filter={`url(#grain-${seed})`}
        />
      </svg>
    </div>
  );
};
