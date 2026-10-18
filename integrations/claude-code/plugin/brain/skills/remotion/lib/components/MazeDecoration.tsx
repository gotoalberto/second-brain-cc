import { useCurrentFrame } from 'remotion';
import React from 'react';

export interface MazeDecorationProps {
  /** Which corner to position the decoration */
  corner?: 'top-right' | 'top-left';
  /** Overall opacity (0-1) */
  opacity?: number;
  /** Scale factor for block size */
  scale?: number;
  /** Primary color for blocks (default: orange #ea580c) */
  primaryColor?: string;
  /** Secondary color for blocks (default: slate #475569) */
  secondaryColor?: string;
  /** Ratio of primary to secondary blocks (0-1, default: 0.55) */
  primaryRatio?: number;
}

// Seeded random for consistent block generation
const seededRandom = (seed: number) => {
  const x = Math.sin(seed * 9301 + 49297) * 49297;
  return x - Math.floor(x);
};

// Derive light and shadow colors from a base color
const deriveColors = (baseColor: string) => {
  // Simple approach: parse hex and adjust brightness
  const hex = baseColor.replace('#', '');
  const r = parseInt(hex.substring(0, 2), 16);
  const g = parseInt(hex.substring(2, 4), 16);
  const b = parseInt(hex.substring(4, 6), 16);

  const lighten = (c: number) => Math.min(255, Math.round(c * 1.3));
  const darken = (c: number) => Math.round(c * 0.6);

  const toHex = (c: number) => c.toString(16).padStart(2, '0');

  return {
    base: baseColor,
    light: `#${toHex(lighten(r))}${toHex(lighten(g))}${toHex(lighten(b))}`,
    shadow: `#${toHex(darken(r))}${toHex(darken(g))}${toHex(darken(b))}`,
  };
};

/**
 * Animated maze/grid decoration for video corners.
 * Creates a grid of blocks with ripple wave animation.
 *
 * @example
 * // Basic usage (top-right corner with default colors)
 * <MazeDecoration />
 *
 * @example
 * // Custom colors matching brand
 * <MazeDecoration
 *   corner="top-left"
 *   primaryColor={theme.colors.primary}
 *   secondaryColor={theme.colors.backgroundDark}
 *   opacity={0.2}
 * />
 */
export const MazeDecoration: React.FC<MazeDecorationProps> = ({
  corner = 'top-right',
  opacity = 0.18,
  scale = 1,
  primaryColor = '#ea580c',
  secondaryColor = '#475569',
  primaryRatio = 0.55,
}) => {
  const frame = useCurrentFrame();

  // Grid settings
  const cols = 9;
  const rows = 7;
  const cellSize = 72 * scale;
  const gap = 8 * scale;

  const isRight = corner === 'top-right';

  // Pre-compute color variations
  const primaryColors = deriveColors(primaryColor);
  const secondaryColors = deriveColors(secondaryColor);

  // Generate block data (deterministic)
  const blocks: {
    row: number;
    col: number;
    isPrimary: boolean;
    phase: number;
    speed: number;
  }[] = [];

  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const seed = r * cols + c;
      if (seededRandom(seed * 7) > 0.25) {
        const distFromCorner = Math.sqrt(
          Math.pow(isRight ? cols - 1 - c : c, 2) + Math.pow(r, 2)
        );
        const phase = distFromCorner * 1.0 + seededRandom(seed * 11) * 2;
        const speed = 0.03 + seededRandom(seed * 13) * 0.02;

        blocks.push({
          row: r,
          col: c,
          isPrimary: seededRandom(seed * 3) > (1 - primaryRatio),
          phase,
          speed,
        });
      }
    }
  }

  const containerStyle: React.CSSProperties = {
    position: 'absolute',
    top: -30,
    [isRight ? 'right' : 'left']: 80,
    width: cols * (cellSize + gap) + 100,
    height: rows * (cellSize + gap) + 100,
    transform: `rotate(${isRight ? -25 : 25}deg) skewY(${isRight ? -8 : 8}deg)`,
    transformOrigin: isRight ? 'top right' : 'top left',
    maskImage: `radial-gradient(ellipse at ${isRight ? 'top right' : 'top left'}, black 20%, transparent 65%)`,
    WebkitMaskImage: `radial-gradient(ellipse at ${isRight ? 'top right' : 'top left'}, black 20%, transparent 65%)`,
  };

  return (
    <div style={containerStyle}>
      {blocks.map((block, i) => {
        const x = block.col * (cellSize + gap) + 50;
        const y = block.row * (cellSize + gap) + 50;

        // Ripple: oscillate between 0 and 1
        const wave = (Math.sin(frame * block.speed + block.phase) + 1) / 2;
        const blockScale = 0.7 + wave * 0.35;
        const blockOpacity = opacity * (0.5 + wave * 0.5);
        const colors = block.isPrimary ? primaryColors : secondaryColors;
        const shadowSpread = wave * 8;

        return (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: x,
              top: y,
              width: cellSize,
              height: cellSize,
              backgroundColor: colors.base,
              borderRadius: 4,
              transform: `scale(${blockScale})`,
              opacity: blockOpacity,
              boxShadow: `0 ${shadowSpread}px ${shadowSpread * 2}px ${colors.shadow}`,
              borderTop: `2px solid ${colors.light}`,
              borderLeft: `1px solid ${colors.light}`,
              transition: 'none',
            }}
          />
        );
      })}
    </div>
  );
};
