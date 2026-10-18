/**
 * RGB Split Transition
 *
 * Chromatic aberration effect that creates color fringing
 * with directional displacement. Creates a modern tech aesthetic
 * reminiscent of CRT displays and analog video glitches.
 *
 * Best for: Tech products, modern branding, energetic transitions
 */
import type {
  TransitionPresentation,
  TransitionPresentationComponentProps,
} from '@remotion/transitions';
import React, { useMemo } from 'react';
import { AbsoluteFill, interpolate } from 'remotion';

export type RgbSplitProps = {
  /** Direction of the split: 'horizontal' | 'vertical' | 'diagonal'. Default: 'horizontal' */
  direction?: 'horizontal' | 'vertical' | 'diagonal';
  /** Maximum pixel displacement. Default: 50 */
  displacement?: number;
};

const RgbSplitPresentation: React.FC<
  TransitionPresentationComponentProps<RgbSplitProps>
> = ({ children, presentationDirection, presentationProgress, passedProps }) => {
  const {
    direction = 'horizontal',
    displacement = 50,
  } = passedProps;

  // Split intensity peaks in the middle of the transition
  const splitIntensity = useMemo(() => {
    return interpolate(presentationProgress, [0, 0.5, 1], [0, 1, 0], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    });
  }, [presentationProgress]);

  // Calculate offset based on direction
  const getOffset = (multiplier: number) => {
    const offset = displacement * splitIntensity * multiplier;
    switch (direction) {
      case 'horizontal':
        return { x: offset, y: 0 };
      case 'vertical':
        return { x: 0, y: offset };
      case 'diagonal':
        return { x: offset * 0.7, y: offset * 0.7 };
    }
  };

  const redOffset = getOffset(-1);
  const cyanOffset = getOffset(1);

  // Simple linear crossfade opacity
  const opacity = presentationDirection === 'exiting'
    ? interpolate(presentationProgress, [0, 1], [1, 0])
    : interpolate(presentationProgress, [0, 1], [0, 1]);

  // Ghost layer opacity based on effect intensity
  const ghostOpacity = splitIntensity * 0.7;

  return (
    <AbsoluteFill>
      {/* Main content layer */}
      <AbsoluteFill style={{ opacity }}>
        {children}
      </AbsoluteFill>

      {/* Red/magenta ghost - offset one direction */}
      {splitIntensity > 0.05 && (
        <AbsoluteFill
          style={{
            opacity: opacity * ghostOpacity,
            transform: `translate(${redOffset.x}px, ${redOffset.y}px)`,
            filter: 'saturate(2) hue-rotate(-30deg) brightness(1.2)',
            mixBlendMode: 'screen',
          }}
        >
          {children}
        </AbsoluteFill>
      )}

      {/* Cyan ghost - offset opposite direction */}
      {splitIntensity > 0.05 && (
        <AbsoluteFill
          style={{
            opacity: opacity * ghostOpacity,
            transform: `translate(${cyanOffset.x}px, ${cyanOffset.y}px)`,
            filter: 'saturate(2) hue-rotate(150deg) brightness(1.2)',
            mixBlendMode: 'screen',
          }}
        >
          {children}
        </AbsoluteFill>
      )}

      {/* Subtle scan line overlay for retro feel */}
      {splitIntensity > 0.3 && (
        <AbsoluteFill
          style={{
            opacity: splitIntensity * 0.15,
            background: `repeating-linear-gradient(
              0deg,
              transparent,
              transparent 2px,
              rgba(0, 0, 0, 0.3) 2px,
              rgba(0, 0, 0, 0.3) 4px
            )`,
            pointerEvents: 'none',
          }}
        />
      )}
    </AbsoluteFill>
  );
};

export const rgbSplit = (
  props: RgbSplitProps = {}
): TransitionPresentation<RgbSplitProps> => {
  return { component: RgbSplitPresentation, props };
};
