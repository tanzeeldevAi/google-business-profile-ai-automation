"use client";

import { scoreColour } from "@/lib/api";

export function Card({
  title, children, right, className = "",
}: {
  title?: string;
  children: React.ReactNode;
  right?: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-xl border border-line bg-panel p-5 ${className}`}>
      {title && (
        <header className="flex items-center gap-3 mb-4">
          <h2 className="text-[11.5px] font-semibold tracking-[0.1em] uppercase text-ink-3">
            {title}
          </h2>
          {right && <div className="ml-auto">{right}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function Button({
  children, onClick, kind = "normal", disabled, title, className = "",
}: {
  children: React.ReactNode;
  onClick?: () => void;
  kind?: "normal" | "primary" | "write";
  disabled?: boolean;
  title?: string;
  className?: string;
}) {
  const styles = {
    normal: "bg-panel-2 border-line hover:border-accent",
    primary: "bg-accent text-base border-accent font-medium hover:opacity-90",
    // Anything that can publish to a live profile is the only thing that gets
    // this colour, so "this writes" is visible before you click.
    write: "bg-panel-2 border-write/60 text-write hover:bg-write/10",
  }[kind];
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`px-3.5 py-2 rounded-lg border text-sm transition disabled:opacity-40 disabled:cursor-not-allowed ${styles} ${className}`}
    >
      {children}
    </button>
  );
}

export function Dial({ score, size = 92 }: { score: number; size?: number }) {
  return (
    <div
      className="rounded-full grid place-items-center font-bold text-base shrink-0"
      style={{ width: size, height: size, background: scoreColour(score), fontSize: size / 3 }}
    >
      {score}
    </div>
  );
}

export function Spark({ points }: { points: { score: number }[] }) {
  if (points.length < 2) return null;
  const max = Math.max(...points.map((p) => p.score), 100);
  return (
    <div className="flex items-end gap-[3px] h-10 mt-3">
      {points.map((p, i) => (
        <i
          key={i}
          title={String(p.score)}
          className="flex-1 rounded-t bg-accent"
          style={{ height: `${Math.max(4, (p.score / max) * 100)}%`, opacity: i === points.length - 1 ? 1 : 0.45 }}
        />
      ))}
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-ink-3 py-6 text-center">{children}</p>;
}

export function Pill({ children, tone = "dim" }: { children: React.ReactNode; tone?: string }) {
  const tones: Record<string, string> = {
    dim: "bg-panel-2 text-ink-3 border-line",
    good: "bg-good/15 text-good border-good/40",
    warn: "bg-warn/15 text-warn border-warn/40",
    bad: "bg-bad/15 text-bad border-bad/40",
    write: "bg-write/15 text-write border-write/40",
  };
  return (
    <span className={`text-[10.5px] uppercase tracking-wider px-2 py-0.5 rounded border ${tones[tone] || tones.dim}`}>
      {children}
    </span>
  );
}
