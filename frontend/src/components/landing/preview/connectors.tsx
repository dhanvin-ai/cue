"use client";

import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

export type Link = { from: string; to: string };

type Path = { key: string; d: string; start: [number, number]; end: [number, number] };

/**
 * Keeps a registry of named elements inside `container` and draws curved
 * lines between pairs of them, so the preview can show Cue pulling a PR or a
 * meeting into its answer.
 */
export function useConnectorRegistry() {
  const nodes = useRef(new Map<string, HTMLElement>());
  const register = useCallback(
    (id: string) => (el: HTMLElement | null) => {
      if (el) nodes.current.set(id, el);
      else if (nodes.current.get(id)?.isConnected === false) nodes.current.delete(id);
    },
    [],
  );
  return { nodes, register };
}

export function Connectors({
  container,
  nodes,
  links,
  revision,
}: {
  container: RefObject<HTMLElement | null>;
  nodes: RefObject<Map<string, HTMLElement>>;
  links: Link[];
  /** Changes whenever the story moves on, so positions are re-measured. */
  revision: string;
}) {
  const [paths, setPaths] = useState<Path[]>([]);
  const [size, setSize] = useState({ w: 0, h: 0 });

  useEffect(() => {
    const root = container.current;
    if (!root) return;

    const measure = () => {
      const box = root.getBoundingClientRect();
      setSize({ w: box.width, h: box.height });
      const next: Path[] = [];
      for (const link of links) {
        const a = nodes.current.get(link.from);
        const b = nodes.current.get(link.to);
        if (!a?.isConnected || !b?.isConnected) continue;
        const ra = a.getBoundingClientRect();
        const rb = b.getBoundingClientRect();
        // Lines run from the side of `from` that faces `to`.
        const aIsRight = ra.left > rb.right;
        const ax = (aIsRight ? ra.left : ra.right) - box.left;
        const ay = ra.top + ra.height / 2 - box.top;
        const bx = (aIsRight ? rb.right : rb.left) - box.left;
        const by = rb.top + Math.min(22, rb.height / 2) - box.top;
        const bend = Math.max(40, Math.abs(ax - bx) * 0.45) * (aIsRight ? -1 : 1);
        next.push({
          key: `${link.from}->${link.to}`,
          d: `M ${ax} ${ay} C ${ax + bend} ${ay}, ${bx - bend} ${by}, ${bx} ${by}`,
          start: [ax, ay],
          end: [bx, by],
        });
      }
      setPaths(next);
    };

    // Messages slide into place over ~0.5s, so measure as they settle.
    const timers = [0, 180, 420, 700].map((t) => setTimeout(measure, t));
    const observer = new ResizeObserver(measure);
    observer.observe(root);
    return () => {
      timers.forEach(clearTimeout);
      observer.disconnect();
    };
  }, [container, nodes, links, revision]);

  return (
    <svg
      aria-hidden
      className="pointer-events-none absolute inset-0 z-30 hidden lg:block"
      width={size.w}
      height={size.h}
      viewBox={`0 0 ${size.w || 1} ${size.h || 1}`}
    >
      <defs>
        <linearGradient id="cue-link" x1="0" x2="1">
          <stop offset="0%" stopColor="#b8d43a" />
          <stop offset="100%" stopColor="#0f100d" stopOpacity="0.55" />
        </linearGradient>
      </defs>
      <AnimatePresence>
        {paths.map((p, i) => (
          <motion.g key={p.key} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, transition: { duration: 0.4 } }}>
            <motion.path
              d={p.d}
              fill="none"
              stroke="url(#cue-link)"
              strokeWidth={1.5}
              strokeDasharray="1 0"
              initial={{ pathLength: 0 }}
              animate={{ pathLength: 1, d: p.d }}
              transition={{ pathLength: { duration: 0.8, delay: i * 0.12, ease: [0.22, 1, 0.36, 1] }, d: { duration: 0.35 } }}
            />
            <circle cx={p.start[0]} cy={p.start[1]} r={3.5} fill="#d9f25c" stroke="#0f100d" strokeWidth={1.25} />
            <circle cx={p.end[0]} cy={p.end[1]} r={2.5} fill="#0f100d" />
            <circle r={3} fill="#d9f25c" stroke="#0f100d" strokeWidth={1}>
              <animateMotion dur="1.5s" begin={`${0.6 + i * 0.12}s`} repeatCount="indefinite" path={p.d} />
            </circle>
          </motion.g>
        ))}
      </AnimatePresence>
    </svg>
  );
}
