/**
 * Animated Envelope Component
 *
 * A 3D envelope that can open/close with a rotating flap animation.
 * Useful for email delivery animations in product demos.
 *
 * @example
 * ```tsx
 * import { Envelope } from '../../../../lib/components';
 *
 * // In your component:
 * const flapOpen = interpolate(frame, [30, 50], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
 *
 * <Envelope
 *   width={600}
 *   height={400}
 *   flapOpen={flapOpen}
 *   message="From Digital Samba, with love"
 *   color="#f5f5dc"
 * />
 * ```
 */

import { interpolate } from 'remotion';

export interface EnvelopeProps {
  /** Width of the envelope in pixels */
  width: number;
  /** Height of the envelope body in pixels */
  height: number;
  /** Flap open state: 0 = closed (flap down), 1 = fully open (flap up) */
  flapOpen: number;
  /** Envelope color (default: cream/beige) */
  color?: string;
  /** Optional message to display on envelope body (bottom-right) */
  message?: string;
  /** Font family for the message */
  messageFont?: string;
  /** Font size for the message */
  messageFontSize?: number;
  /** Show postage stamp in top-right corner */
  showStamp?: boolean;
  /** Show faded address lines in center */
  showAddressLines?: boolean;
}

export const Envelope: React.FC<EnvelopeProps> = ({
  width,
  height,
  flapOpen,
  color = '#f5f5dc',
  message,
  messageFont = 'Georgia, serif',
  messageFontSize = 16,
  showStamp = false,
  showAddressLines = false,
}) => {
  const flapHeight = height * 0.4;
  // flapOpen: 0 = closed (rotated down), 1 = open (rotated up/back)
  const flapRotation = interpolate(flapOpen, [0, 1], [-180, 0]);

  return (
    <div style={{ position: 'relative', width, height }}>
      {/* Envelope body */}
      <div
        style={{
          position: 'absolute',
          width: '100%',
          height: '100%',
          background: `linear-gradient(180deg, ${color} 0%, #e8e8d0 100%)`,
          borderRadius: 8,
          boxShadow: '0 8px 32px rgba(0,0,0,0.3)',
        }}
      />

      {/* Inner shadow/depth */}
      <div
        style={{
          position: 'absolute',
          top: flapHeight * 0.5,
          left: 10,
          right: 10,
          bottom: 10,
          background: 'rgba(0,0,0,0.05)',
          borderRadius: 4,
        }}
      />

      {/* Postage stamp - top right */}
      {showStamp && (
        <div
          style={{
            position: 'absolute',
            top: 120,
            right: 25,
            width: width * 0.12,
            height: width * 0.14,
            background: 'linear-gradient(135deg, #e8d4b8 0%, #d4c4a8 50%, #c8b898 100%)',
            border: '2px solid rgba(120, 90, 60, 0.3)',
            borderRadius: 2,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '1px 2px 4px rgba(0,0,0,0.15)',
            transform: 'rotate(2deg)',
          }}
        >
          {/* Stamp perforated edge effect */}
          <div
            style={{
              position: 'absolute',
              inset: -4,
              background: `radial-gradient(circle at 0% 50%, transparent 3px, ${color} 3px) left / 8px 100%,
                          radial-gradient(circle at 100% 50%, transparent 3px, ${color} 3px) right / 8px 100%,
                          radial-gradient(circle at 50% 0%, transparent 3px, ${color} 3px) top / 100% 8px,
                          radial-gradient(circle at 50% 100%, transparent 3px, ${color} 3px) bottom / 100% 8px`,
              backgroundRepeat: 'no-repeat',
              pointerEvents: 'none',
            }}
          />
          {/* Stamp design - simple EU-style */}
          <div
            style={{
              width: '70%',
              height: '50%',
              borderRadius: '50%',
              border: '2px solid rgba(70, 50, 30, 0.4)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              marginBottom: 4,
            }}
          >
            <span style={{ fontSize: width * 0.025, color: 'rgba(70, 50, 30, 0.5)' }}>✦</span>
          </div>
          {/* Stamp value */}
          <span
            style={{
              fontSize: width * 0.018,
              fontFamily: 'Georgia, serif',
              color: 'rgba(70, 50, 30, 0.6)',
              fontWeight: 600,
            }}
          >
            EU
          </span>
        </div>
      )}

      {/* Faded scribble address lines - center */}
      {showAddressLines && (
        <div
          style={{
            position: 'absolute',
            top: 'calc(45% + 50px)',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            display: 'flex',
            flexDirection: 'column',
            gap: 12,
            width: '50%',
          }}
        >
          {/* Line 1 - name (shorter) */}
          <div
            style={{
              height: 10,
              background: 'linear-gradient(90deg, transparent 5%, rgba(80, 60, 40, 0.25) 15%, rgba(80, 60, 40, 0.3) 50%, rgba(80, 60, 40, 0.2) 80%, transparent 95%)',
              borderRadius: 3,
              width: '65%',
              marginLeft: '5%',
              transform: 'rotate(-0.5deg)',
            }}
          />
          {/* Line 2 - street (longer) */}
          <div
            style={{
              height: 10,
              background: 'linear-gradient(90deg, transparent 3%, rgba(80, 60, 40, 0.2) 10%, rgba(80, 60, 40, 0.35) 40%, rgba(80, 60, 40, 0.25) 70%, rgba(80, 60, 40, 0.15) 90%, transparent 97%)',
              borderRadius: 3,
              width: '90%',
              transform: 'rotate(0.3deg)',
            }}
          />
          {/* Line 3 - city/country (medium) */}
          <div
            style={{
              height: 10,
              background: 'linear-gradient(90deg, transparent 8%, rgba(80, 60, 40, 0.22) 18%, rgba(80, 60, 40, 0.28) 45%, rgba(80, 60, 40, 0.18) 75%, transparent 92%)',
              borderRadius: 3,
              width: '75%',
              marginLeft: '8%',
              transform: 'rotate(-0.2deg)',
            }}
          />
        </div>
      )}

      {/* Optional message on envelope */}
      {message && (
        <div
          style={{
            position: 'absolute',
            bottom: 30,
            right: 30,
            fontSize: messageFontSize,
            fontFamily: messageFont,
            fontStyle: 'italic',
            color: 'rgba(90, 70, 50, 0.8)',
            letterSpacing: 0.5,
          }}
        >
          {message}
        </div>
      )}

      {/* Envelope flap - positioned above envelope body, hinges from top edge */}
      <div
        style={{
          position: 'absolute',
          top: -flapHeight,
          left: 0,
          width: '100%',
          height: flapHeight,
          transformOrigin: 'bottom center',
          transform: `rotateX(${flapRotation}deg)`,
          transformStyle: 'preserve-3d',
          // When closed (flapOpen < 0.5), flap is behind; when open, flap is in front
          zIndex: flapOpen < 0.5 ? -1 : 2,
        }}
      >
        {/* Flap front - triangle: base at bottom, tip pointing up */}
        <div
          style={{
            position: 'absolute',
            width: '100%',
            height: '100%',
            background: `linear-gradient(0deg, ${color} 0%, #e0e0c8 100%)`,
            clipPath: 'polygon(0 100%, 50% 0, 100% 100%)',
            backfaceVisibility: 'hidden',
          }}
        />
        {/* Flap back (visible when opened/rotated) */}
        <div
          style={{
            position: 'absolute',
            width: '100%',
            height: '100%',
            background: `linear-gradient(180deg, #c8c8b0 0%, #d8d8c0 100%)`,
            clipPath: 'polygon(0 100%, 50% 0, 100% 100%)',
            transform: 'rotateX(180deg)',
            backfaceVisibility: 'hidden',
          }}
        />
      </div>
    </div>
  );
};
