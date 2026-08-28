"use client";

import { useCallback, useRef, useState } from "react";

/* Google's own components, rebuilt: filled/tonal/outlined/text buttons with a
   real ripple, Material cards, chips, an indeterminate progress bar, and an
   animated score dial. Everything moves on Material's easing curve, which is
   most of why a Google surface feels calm instead of springy. */

// ------------------------------------------------------------------- button

type ButtonKind = "filled" | "tonal" | "outlined" | "text" | "danger";

export function Button({
  children, onClick, kind = "outlined", disabled, title, icon, className = "",
  type = "button", full,
}: {
  children?: React.ReactNode;
  onClick?: () => void;
  kind?: ButtonKind;
  disabled?: boolean;
  title?: string;
  icon?: React.ReactNode;
  className?: string;
  type?: "button" | "submit";
  full?: boolean;
}) {
  const ref = useRef<HTMLButtonElement>(null);
  const [ripples, setRipples] = useState<{ id: number; x: number; y: number }[]>([]);

  // A real ripple from the click point. Material's tell, and the cheapest way
  // to make a button feel like a Google button rather than a styled div.
  const press = useCallback((e: React.MouseEvent) => {
    const el = ref.current;
    if (!el) return;
    const box = el.getBoundingClientRect();
    const id = Date.now();
    setRipples((r) => [...r, { id, x: e.clientX - box.left, y: e.clientY - box.top }]);
    setTimeout(() => setRipples((r) => r.filter((x) => x.id !== id)), 520);
  }, []);

  const styles: Record<ButtonKind, string> = {
    filled: "bg-g-blue text-white hover:bg-g-blueHover shadow-e1 hover:shadow-e2 border-transparent",
    tonal: "bg-g-blueLight text-g-blue hover:bg-[#d7e6fd] border-transparent",
    outlined: "bg-white text-g-blue border-g-grey300 hover:bg-g-blueLight/50",
    text: "bg-transparent text-g-blue border-transparent hover:bg-g-blueLight/60",
    danger: "bg-white text-g-red border-g-grey300 hover:bg-g-redLight",
  };

  return (
    <button
      ref={ref}
      type={type}
      title={title}
      disabled={disabled}
      onClick={(e) => { if (!disabled) { press(e); onClick?.(); } }}
      className={`relative overflow-hidden inline-flex items-center justify-center gap-2
        rounded-pill border px-6 h-10 text-sm font-medium font-sans
        transition-[background-color,box-shadow,border-color] duration-200
        disabled:opacity-40 disabled:cursor-not-allowed disabled:shadow-none
        ${styles[kind]} ${full ? "w-full" : ""} ${className}`}
      style={{ transitionTimingFunction: "cubic-bezier(.4,0,.2,1)" }}
    >
      {icon}
      {children}
      {ripples.map((r) => (
        <span
          key={r.id}
          className="pointer-events-none absolute rounded-full bg-current animate-ripple-out"
          style={{ left: r.x - 50, top: r.y - 50, width: 100, height: 100 }}
        />
      ))}
    </button>
  );
}

// --------------------------------------------------------------------- card

export function Card({
  title, subtitle, children, right, className = "", pad = true,
}: {
  title?: string;
  subtitle?: string;
  children: React.ReactNode;
  right?: React.ReactNode;
  className?: string;
  pad?: boolean;
}) {
  return (
    <section
      className={`bg-white rounded-g border border-g-grey300 shadow-e1
        transition-shadow duration-200 hover:shadow-e2 animate-fade-up ${className}`}
      style={{ transitionTimingFunction: "cubic-bezier(.4,0,.2,1)" }}
    >
      {(title || right) && (
        <header className={`flex items-start gap-3 ${pad ? "px-6 pt-5" : "px-4 pt-4"}`}>
          <div className="min-w-0">
            {title && (
              <h2 className="font-sans text-base font-medium text-g-grey900">{title}</h2>
            )}
            {subtitle && (
              <p className="text-[13px] text-g-grey600 mt-0.5">{subtitle}</p>
            )}
          </div>
          {right && <div className="ml-auto shrink-0">{right}</div>}
        </header>
      )}
      <div className={pad ? "px-6 py-5" : "p-4"}>{children}</div>
    </section>
  );
}

// -------------------------------------------------------------------- chips

type Tone = "neutral" | "blue" | "green" | "yellow" | "red";

const TONE: Record<Tone, string> = {
  neutral: "bg-g-grey100 text-g-grey700 border-g-grey300",
  blue: "bg-g-blueLight text-g-blue border-transparent",
  green: "bg-g-greenLight text-g-green border-transparent",
  yellow: "bg-g-yellowLight text-[#b06000] border-transparent",
  red: "bg-g-redLight text-g-red border-transparent",
};

export function Chip({
  children, tone = "neutral", icon,
}: {
  children: React.ReactNode;
  tone?: Tone;
  icon?: React.ReactNode;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-pill border px-2.5 h-6
        text-[11px] font-medium tracking-wide ${TONE[tone]}`}
    >
      {icon}
      {children}
    </span>
  );
}

export const SEVERITY_TONE: Record<string, Tone> = {
  critical: "red", high: "yellow", medium: "blue", low: "neutral",
};

// ----------------------------------------------------------------- progress

export function Progress({ indeterminate = true, value = 0 }: {
  indeterminate?: boolean; value?: number;
}) {
  return (
    <div className="relative h-1 w-full overflow-hidden rounded-pill bg-g-blueLight">
      {indeterminate ? (
        <span className="absolute inset-y-0 bg-g-blue animate-indeterminate rounded-pill" />
      ) : (
        <span
          className="absolute inset-y-0 left-0 bg-g-blue rounded-pill transition-[width] duration-300"
          style={{ width: `${Math.max(0, Math.min(100, value))}%`,
                   transitionTimingFunction: "cubic-bezier(.4,0,.2,1)" }}
        />
      )}
    </div>
  );
}

// --------------------------------------------------------------------- dial

export function Dial({ score, size = 104 }: { score: number; size?: number }) {
  const stroke = 8;
  const r = (size - stroke) / 2;
  const circumference = 2 * Math.PI * r;
  const colour = score >= 75 ? "#1e8e3e" : score >= 50 ? "#f9ab00" : "#d93025";
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none"
                stroke="#e8eaed" strokeWidth={stroke} />
        <circle
          cx={size / 2} cy={size / 2} r={r} fill="none" stroke={colour}
          strokeWidth={stroke} strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - score / 100)}
          style={{ transition: "stroke-dashoffset 1s cubic-bezier(.4,0,.2,1)" }}
        />
      </svg>
      <div className="absolute inset-0 grid place-items-center">
        <span className="font-sans font-medium text-g-grey900"
              style={{ fontSize: size / 3.2 }}>{score}</span>
      </div>
    </div>
  );
}

// -------------------------------------------------------------------- misc

export function Spark({ points }: { points: { score: number }[] }) {
  if (points.length < 2) return null;
  const max = Math.max(...points.map((p) => p.score), 100);
  return (
    <div className="flex items-end gap-1 h-10">
      {points.map((p, i) => (
        <span
          key={i}
          title={String(p.score)}
          className="flex-1 rounded-t-sm bg-g-blue transition-all duration-500"
          style={{
            height: `${Math.max(6, (p.score / max) * 100)}%`,
            opacity: i === points.length - 1 ? 1 : 0.3 + (i / points.length) * 0.5,
            transitionTimingFunction: "cubic-bezier(.4,0,.2,1)",
          }}
        />
      ))}
    </div>
  );
}

export function Empty({ children, icon }: { children: React.ReactNode; icon?: string }) {
  return (
    <div className="py-10 text-center">
      {icon && <div className="text-3xl mb-2 opacity-40">{icon}</div>}
      <p className="text-sm text-g-grey600">{children}</p>
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div className={`animate-pulse rounded bg-g-grey200 ${className}`} />
  );
}

export function Banner({
  tone = "yellow", title, children, action,
}: {
  tone?: Tone;
  title?: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  const border: Record<Tone, string> = {
    neutral: "border-l-g-grey500", blue: "border-l-g-blue",
    green: "border-l-g-green", yellow: "border-l-g-yellow", red: "border-l-g-red",
  };
  return (
    <div className={`rounded-g border border-g-grey300 border-l-4 ${border[tone]}
      bg-white shadow-e1 px-4 py-3 flex items-start gap-3 animate-fade-up`}>
      <div className="min-w-0 flex-1">
        {title && <p className="font-sans font-medium text-sm text-g-grey900">{title}</p>}
        <div className="text-[13px] text-g-grey700 leading-relaxed">{children}</div>
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

export function Switch({
  checked, onChange, label, hint, disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  hint?: string;
  disabled?: boolean;
}) {
  return (
    <label className={`flex items-start gap-3 py-2 ${disabled ? "opacity-50" : "cursor-pointer"}`}>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => !disabled && onChange(!checked)}
        className={`relative mt-0.5 h-4 w-9 shrink-0 rounded-pill transition-colors duration-200
          ${checked ? "bg-g-blue/50" : "bg-g-grey300"}`}
        style={{ transitionTimingFunction: "cubic-bezier(.4,0,.2,1)" }}
      >
        <span
          className={`absolute -top-1 h-6 w-6 rounded-full shadow-e1 transition-transform duration-200
            ${checked ? "translate-x-4 bg-g-blue" : "translate-x-0 bg-white border border-g-grey300"}`}
          style={{ transitionTimingFunction: "cubic-bezier(.4,0,.2,1)" }}
        />
      </button>
      <span className="min-w-0">
        <span className="text-sm text-g-grey900">{label}</span>
        {hint && <span className="block text-[12.5px] text-g-grey600">{hint}</span>}
      </span>
    </label>
  );
}

export function TextField({
  label, value, onChange, placeholder, hint, multiline, rows = 4, mono,
}: {
  label?: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  hint?: string;
  multiline?: boolean;
  rows?: number;
  mono?: boolean;
}) {
  const cls = `w-full rounded-g border border-g-grey300 bg-white px-3 py-2.5 text-sm
    text-g-grey900 placeholder:text-g-grey500 outline-none transition-colors duration-150
    hover:border-g-grey500 focus:border-g-blue focus:ring-1 focus:ring-g-blue
    ${mono ? "font-mono text-[13px]" : ""}`;
  return (
    <label className="block mb-4">
      {label && <span className="mb-1.5 block text-[13px] font-medium text-g-grey700">{label}</span>}
      {multiline ? (
        <textarea rows={rows} value={value} placeholder={placeholder}
                  onChange={(e) => onChange(e.target.value)}
                  className={`${cls} resize-y`} />
      ) : (
        <input type="text" value={value} placeholder={placeholder}
               onChange={(e) => onChange(e.target.value)} className={cls} />
      )}
      {hint && <span className="mt-1 block text-[12px] text-g-grey600">{hint}</span>}
    </label>
  );
}
