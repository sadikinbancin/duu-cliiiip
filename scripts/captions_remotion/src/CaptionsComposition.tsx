import React, { useMemo } from "react";
import {
  AbsoluteFill,
  Sequence,
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  spring,
  Easing,
} from "remotion";

// Types
export interface CaptionWord {
  word: string;
  start: number;  // seconds
  end: number;    // seconds
}

export interface CaptionEvent {
  words: CaptionWord[];
  start: number;
  end: number;
  text: string;
}

export interface CaptionStyle {
  fontFamily: string;
  fontSize: number;
  color: string;
  activeColor?: string;
  keywordColor?: string;
  outlineColor: string;
  outlineWidth: number;
  shadowColor?: string;
  shadowBlur?: number;
  alignment: "left" | "center" | "right";
  position: "top" | "middle" | "bottom";
  marginV: number;
  marginL: number;
  marginR: number;
  uppercase?: boolean;
}

export interface CaptionsCompositionProps {
  events: CaptionEvent[];
  style: CaptionStyle;
  styleSlug?: string;
}

// Parse word-level transcript into caption events (max 2 lines, ~6 words per line)
function parseEvents(words: CaptionWord[], maxWordsPerLine: number = 6): CaptionEvent[] {
  if (!words || words.length === 0) return [];

  const events: CaptionEvent[] = [];
  let currentBatch: CaptionWord[] = [];

  for (const w of words) {
    currentBatch.push(w);
    if (currentBatch.length >= maxWordsPerLine) {
      events.push({
        words: [...currentBatch],
        start: currentBatch[0].start,
        end: currentBatch[currentBatch.length - 1].end,
        text: currentBatch.map((cw) => cw.word).join(" "),
      });
      currentBatch = [];
    }
  }

  if (currentBatch.length > 0) {
    events.push({
      words: [...currentBatch],
      start: currentBatch[0].start,
      end: currentBatch[currentBatch.length - 1].end,
      text: currentBatch.map((cw) => cw.word).join(" "),
    });
  }

  return events;
}

// Clean filler words from transcript
const FILLER_WORDS = new Set(["um", "uh", "you know", "like", "i mean", "sort of", "kind of"]);

function cleanWord(word: string): string {
  const lower = word.toLowerCase().trim();
  if (FILLER_WORDS.has(lower)) return "";
  return word;
}

// Single caption event renderer
const CaptionEventComp: React.FC<{
  event: CaptionEvent;
  style: CaptionStyle;
  styleSlug: string;
}> = ({ event, style, styleSlug }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const startFrame = Math.round(event.start * fps);
  const endFrame = Math.round(event.end * fps);
  const duration = endFrame - startFrame;

  // Pop-in animation
  const enterProgress = spring({
    frame: frame - startFrame,
    fps,
    config: { damping: 200, stiffness: 200 },
    durationInFrames: 4,
  });

  // Exit animation
  const exitProgress = interpolate(
    frame,
    [endFrame - 4, endFrame],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const opacity = Math.min(enterProgress, exitProgress);
  const scale = 0.85 + 0.15 * enterProgress;

  // Bounce style: add per-word highlight
  const isBounce = styleSlug === "bounce" || style.fontFamily.includes("Impact");

  // Y position based on setting
  let yPos = 1420; // bottom default (1920 - 500)
  if (style.position === "top") yPos = 200;
  else if (style.position === "middle") yPos = 960;
  else yPos = 1920 - style.marginV;

  const text = style.uppercase ? event.text.toUpperCase() : event.text;

  return (
    <AbsoluteFill
      style={{
        opacity,
        transform: `scale(${scale})`,
        justifyContent: "center",
        alignItems: style.alignment === "center" ? "center" : style.alignment === "right" ? "flex-end" : "flex-start",
        paddingLeft: style.marginL,
        paddingRight: style.marginR,
        paddingTop: style.position === "top" ? style.marginV : undefined,
        paddingBottom: style.position === "bottom" ? style.marginV : undefined,
      }}
    >
      <div
        style={{
          fontFamily: style.fontFamily,
          fontSize: style.fontSize,
          color: style.color,
          textAlign: style.alignment,
          lineHeight: 1.3,
          WebkitTextStroke: `${style.outlineWidth}px ${style.outlineColor}`,
          paintOrder: "stroke fill",
          textShadow: style.shadowColor
            ? `0 0 ${style.shadowBlur || 2}px ${style.shadowColor}, 0 2px 4px rgba(0,0,0,0.8)`
            : `0 2px 4px rgba(0,0,0,0.8)`,
          maxWidth: 1080 - style.marginL - style.marginR,
          wordBreak: "break-word",
        }}
      >
        {isBounce ? (
          <BounceWords event={event} style={style} />
        ) : style.activeColor ? (
          <BoldWords event={event} style={style} />
        ) : (
          text
        )}
      </div>
    </AbsoluteFill>
  );
};

// Bold style: highlight active word
const BoldWords: React.FC<{ event: CaptionEvent; style: CaptionStyle }> = ({
  event,
  style,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  return (
    <span>
      {event.words.map((w, i) => {
        const wordStart = Math.round(w.start * fps);
        const wordEnd = Math.round(w.end * fps);
        const isActive = frame >= wordStart && frame <= wordEnd;

        return (
          <span
            key={i}
            style={{
              color: isActive ? (style.activeColor || "#FFD700") : style.color,
              transition: "color 0.1s",
            }}
          >
            {i > 0 ? " " : ""}
            {w.word}
          </span>
        );
      })}
    </span>
  );
};

// Bounce style: animated per-word pop with color cycling
const BounceWords: React.FC<{ event: CaptionEvent; style: CaptionStyle }> = ({
  event,
  style,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const BOUNCE_COLORS = [
    "#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4",
    "#FFEAA7", "#DDA0DD", "#98D8C8", "#F7DC6F",
  ];

  return (
    <span>
      {event.words.map((w, i) => {
        const wordStart = Math.round(w.start * fps);
        const wordEnd = Math.round(w.end * fps);
        const isActive = frame >= wordStart && frame <= wordEnd;

        const bounceScale = isActive
          ? spring({
              frame: frame - wordStart,
              fps,
              config: { damping: 12, mass: 0.8 },
              durationInFrames: 8,
            })
          : 1;

        const colorIdx = i % BOUNCE_COLORS.length;

        return (
          <span
            key={i}
            style={{
              display: "inline-block",
              color: isActive ? BOUNCE_COLORS[colorIdx] : style.color,
              transform: isActive ? `scale(${bounceScale})` : "scale(1)",
              transition: "transform 0.1s",
            }}
          >
            {i > 0 ? " " : ""}
            {w.word}
          </span>
        );
      })}
    </span>
  );
};

// Main composition
export const CaptionsComposition: React.FC<CaptionsCompositionProps> = ({
  events,
  style,
  styleSlug = "default",
}) => {
  return (
    <AbsoluteFill style={{ backgroundColor: "transparent" }}>
      <Series>
        {events.map((event, i) => (
          <Sequence
            key={i}
            from={Math.round(event.start * 30)}
            durationInFrames={Math.round((event.end - event.start) * 30)}
          >
            <CaptionEventComp
              event={event}
              style={style}
              styleSlug={styleSlug}
            />
          </Sequence>
        ))}
      </Series>
    </AbsoluteFill>
  );
};
