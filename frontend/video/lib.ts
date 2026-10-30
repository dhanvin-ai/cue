import { Easing, interpolate } from "remotion";

export const FPS = 30;
export const WIDTH = 1920;
export const HEIGHT = 1080;
export const DURATION = 20 * FPS;

export const easeOut = Easing.bezier(0.22, 1, 0.36, 1);
export const easeInOut = Easing.bezier(0.65, 0, 0.35, 1);
export const easeIn = Easing.bezier(0.55, 0, 0.75, 0.2);

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

/** 0 → 1 over `dur` frames starting at `start`. */
export function prog(f: number, start: number, dur = 18, easing = easeOut) {
  return interpolate(f, [start, start + dur], [0, 1], { ...clamp, easing });
}

/** Piecewise value through `[frame, value]` keys, eased per segment. */
export function track(f: number, keys: readonly (readonly [number, number])[], easing = easeInOut) {
  return interpolate(
    f,
    keys.map((k) => k[0]),
    keys.map((k) => k[1]),
    { ...clamp, easing },
  );
}

export const mix = (a: number, b: number, t: number) => a + (b - a) * t;

/** Every shot names the stage point the camera centres on, and how close it is. */
export type Shot = { f: number; x: number; y: number; s: number };

export function camera(f: number, shots: readonly Shot[], easing = easeInOut) {
  const at = (k: "x" | "y" | "s") => track(f, shots.map((s) => [s.f, s[k]] as const), easing);
  const s = at("s");
  return {
    transform: `translate(${WIDTH / 2 - at("x") * s}px, ${HEIGHT / 2 - at("y") * s}px) scale(${s})`,
    transformOrigin: "0 0",
  } as const;
}

/** How many words of `text` are on screen, one every `perWord` frames from `start`. */
export function wordsShown(f: number, start: number, text: string, perWord = 3) {
  const total = text.split(" ").length;
  return Math.max(0, Math.min(total, Math.floor((f - start) / perWord) + 1));
}

/** Greedy word wrap. Stable as words are appended, so live captions never reflow. */
export function wrap(words: string[], maxChars: number) {
  const lines: string[] = [];
  for (const word of words) {
    const last = lines.at(-1);
    if (last !== undefined && last.length + 1 + word.length <= maxChars) lines[lines.length - 1] = `${last} ${word}`;
    else lines.push(word);
  }
  return lines;
}

/** Story beats, shown in the progress strip along the bottom. */
export const chapters = [
  { at: 0, label: "Invited" },
  { at: 96, label: "Joins" },
  { at: 184, label: "Answers" },
  { at: 334, label: "Shares" },
  { at: 416, label: "Follows up" },
  { at: 500, label: "Zoom too" },
] as const;

/** Windows sit in the same frame across scenes so the camera has a fixed stage. */
export const frame = { x: 180, y: 84, w: 1560, h: 870, bar: 52 } as const;
