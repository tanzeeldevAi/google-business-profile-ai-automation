"use client";

import { ReactNode } from "react";
import { useApp } from "@/components/Shell";
import { Banner, Button, Card, Empty } from "@/components/ui";

/**
 * The shape every "do a thing" screen shares: explain it, offer the controls,
 * then a preview button and — only where the command can write — an Apply
 * button that confirms by business name first.
 *
 * Output goes to the drawer at the bottom of the window, which every screen
 * shares, so a job started here stays visible while you navigate.
 */
export default function ActionPage({
  title, lead, command, options = {}, writes = false, controls, children,
  previewLabel = "Preview", applyLabel = "Apply for real", disabled, disabledWhy,
}: {
  title: string;
  lead: ReactNode;
  command: string;
  options?: Record<string, unknown>;
  writes?: boolean;
  controls?: ReactNode;
  children?: ReactNode;
  previewLabel?: string;
  applyLabel?: string;
  disabled?: boolean;
  disabledWhy?: string;
}) {
  const { active, run, running } = useApp();
  if (!active) return <Empty>Pick a business first.</Empty>;

  return (
    <div className="space-y-4 max-w-4xl">
      <Card title={title}>
        <div className="mb-4 space-y-2 text-sm text-g-grey700">{lead}</div>
        {controls}
        <div className="flex gap-2 flex-wrap mt-4">
          <Button
            kind="filled"
            disabled={running || disabled}
            title={disabledWhy}
            onClick={() => run(command, options, false)}
          >
            {previewLabel}
          </Button>
          {writes && (
            <Button
              kind="danger"
              disabled={running || disabled}
              title={disabledWhy}
              onClick={() => {
                if (
                  confirm(
                    `This WRITES to the live profile:\n\n  ${active.title}\n\n` +
                      `Command: ${command} --apply\n\nGo ahead?`,
                  )
                ) {
                  run(command, options, true);
                }
              }}
            >
              {applyLabel}
            </Button>
          )}
        </div>
        {writes && (
          <p className="mt-3 text-[12.5px] text-g-grey600">
            Preview shows exactly what would change and writes nothing.
          </p>
        )}
        {disabled && disabledWhy && (
          <p className="mt-3 text-[12.5px] text-[#b06000]">{disabledWhy}</p>
        )}
      </Card>
      {children}
    </div>
  );
}

export function Field({
  label, value, onChange, placeholder, hint,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  hint?: string;
}) {
  return (
    <label className="block mb-3">
      <span className="text-sm text-g-grey700">{label}</span>
      <input
        type="text"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded-lg bg-white border border-g-grey300 px-3 py-2 text-sm outline-none focus:border-g-blue"
      />
      {hint && <span className="text-xs text-g-grey600 block mt-1">{hint}</span>}
    </label>
  );
}

export function Toggle({
  label, checked, onChange, hint,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  hint?: string;
}) {
  return (
    <label className="flex items-start gap-2.5 mb-2.5 cursor-pointer">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 w-4 h-4 accent-[#7C9CF5]"
      />
      <span className="text-sm">
        {label}
        {hint && <span className="block text-xs text-g-grey600">{hint}</span>}
      </span>
    </label>
  );
}
