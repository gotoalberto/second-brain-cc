/**
 * Animated Pointing Hand Component
 *
 * An animated hand emoji that slides in from a direction and points at a target.
 * Includes optional pulsing animation after arrival.
 *
 * @example
 * ```tsx
 * import { PointingHand } from '../../../../lib/components';
 *
 * // Position relative to parent container
 * <div style={{ position: 'relative' }}>
 *   <YourContent />
 *   <PointingHand
 *     direction="left"
 *     x={35}
 *     y={50}
 *     size={120}
 *     delay={40}
 *   />
 * </div>
 * ```
 */

import { useCurrentFrame, useVideoConfig, spring, interpolate } from 'remotion';

export interface PointingHandProps {
  /** Direction the hand points (and slides in from the opposite direction) */
  direction: 'left' | 'right' | 'up' | 'down';
  /** X position as percentage (0-100) from left edge of parent */
  x: number;
  /** Y position as percentage (0-100) from top edge of parent */
  y: number;
  /** Size of the hand emoji in pixels (default: 120) */
  size?: number;
  /** Frame delay before hand starts appearing (default: 0) */
  delay?: number;
  /** Enable pulse animation after hand arrives (default: true) */
  pulse?: boolean;
  /** Pulse intensity in pixels (default: 3) */
  pulseIntensity?: number;
  /** Custom hand emoji (default: based on direction) */
  emoji?: string;
  /** Drop shadow settings */
  shadow?: boolean;
}

const directionEmojis: Record<string, string> = {
  left: '👈',
  right: '👉',
  up: '👆',
  down: '👇',
};

export const PointingHand: React.FC<PointingHandProps> = ({
  direction,
  x,
  y,
  size = 120,
  delay = 0,
  pulse = true,
  pulseIntensity = 3,
  emoji,
  shadow = true,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Spring animation for hand entrance
  const handProgress = spring({
    frame: frame - delay,
    fps,
    config: {
      damping: 15,
      stiffness: 80,
      mass: 0.8,
    },
  });

  // Calculate slide distance based on direction
  const slideDistance = 200;
  let translateX = 0;
  let translateY = 0;

  switch (direction) {
    case 'right':
      // Points right, slides in from left
      translateX = interpolate(handProgress, [0, 1], [-slideDistance, 0]);
      break;
    case 'left':
      // Points left, slides in from right
      translateX = interpolate(handProgress, [0, 1], [slideDistance, 0]);
      break;
    case 'down':
      // Points down, slides in from top
      translateY = interpolate(handProgress, [0, 1], [-slideDistance, 0]);
      break;
    case 'up':
      // Points up, slides in from bottom
      translateY = interpolate(handProgress, [0, 1], [slideDistance, 0]);
      break;
  }

  // Opacity fade in
  const opacity = interpolate(frame - delay, [0, 10], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  // Pulse animation after hand arrives
  const pulseFrame = Math.max(0, frame - delay - 30);
  const pulseOffset = pulse ? Math.sin(pulseFrame * 0.15) * pulseIntensity : 0;

  // Apply pulse in the direction of pointing
  if (direction === 'right' || direction === 'left') {
    translateX += pulseOffset * (direction === 'right' ? 1 : -1);
  } else {
    translateY += pulseOffset * (direction === 'down' ? 1 : -1);
  }

  // Determine transform origin based on direction
  let transformOrigin = 'center';
  let offsetTransform = '';
  switch (direction) {
    case 'right':
      transformOrigin = 'left center';
      offsetTransform = 'translate(-100%, -50%)';
      break;
    case 'left':
      transformOrigin = 'right center';
      offsetTransform = 'translate(0%, -50%)';
      break;
    case 'up':
      transformOrigin = 'center bottom';
      offsetTransform = 'translate(-50%, 0%)';
      break;
    case 'down':
      transformOrigin = 'center top';
      offsetTransform = 'translate(-50%, -100%)';
      break;
  }

  const handEmoji = emoji || directionEmojis[direction];

  return (
    <div
      style={{
        position: 'absolute',
        left: `${x}%`,
        top: `${y}%`,
        transform: `${offsetTransform} translate(${translateX}px, ${translateY}px)`,
        transformOrigin,
        opacity,
        fontSize: size,
        filter: shadow ? 'drop-shadow(0 6px 12px rgba(0,0,0,0.4))' : undefined,
        zIndex: 10,
        pointerEvents: 'none',
      }}
    >
      {handEmoji}
    </div>
  );
};
