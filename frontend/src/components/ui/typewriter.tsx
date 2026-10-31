"use client";

import { useEffect, useState } from "react";

/** Reveals `text` character by character over `ms`. Remount (via `key`) to replay. */
export function Typewriter({ text, ms }: { text: string; ms: number }) {
  const count = useReveal(text.length, ms);
  return <>{text.slice(0, count)}</>;
}

/**
 * Reveals `text` word by word over `ms`, like live captions. The newest word
 * is drawn brighter so the eye follows the speech.
 */
export function SpokenWords({ text, ms, className }: { text: string; ms: number; className?: string }) {
  const words = text.split(" ");
  const count = useReveal(words.length, ms);
  return (
    <span className={className}>
      {words.slice(0, count).map((word, i) => (
        <span key={i} className={i === count - 1 ? "text-white" : undefined}>
          {word}{" "}
        </span>
      ))}
    </span>
  );
}

function useReveal(total: number, ms: number) {
  const [count, setCount] = useState(0);
  useEffect(() => {
    const started = performance.now();
    let frame = requestAnimationFrame(function tick(now) {
      const next = Math.min(total, Math.ceil(((now - started) / ms) * total));
      setCount(next);
      if (next < total) frame = requestAnimationFrame(tick);
    });
    return () => cancelAnimationFrame(frame);
  }, [total, ms]);
  return count;
}
