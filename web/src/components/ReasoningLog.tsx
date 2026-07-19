"use client";

import { useState } from "react";

interface LogEntry {
  step: string;
  tool: string;
  input: Record<string, unknown>;
  output: unknown;
  timestamp: string;
}

const TOOL_COLOR: Record<string, { badge: string; line: string }> = {
  lookup_customer:     { badge: "border-accent/40 text-accent bg-accent/10",            line: "bg-accent" },
  lookup_order:        { badge: "border-accent-light/40 text-accent-light bg-accent-light/10", line: "bg-accent-light" },
  check_refund_policy: { badge: "border-warning/40 text-warning bg-warning/10",         line: "bg-warning" },
  process_refund:      { badge: "border-success/40 text-success bg-success/10",         line: "bg-success" },
  deny_refund:         { badge: "border-danger/40 text-danger bg-danger/10",            line: "bg-danger" },
};

const TOOL_LABEL: Record<string, string> = {
  lookup_customer:     "Lookup Customer",
  lookup_order:        "Lookup Order",
  check_refund_policy: "Check Policy",
  process_refund:      "Process Refund",
  deny_refund:         "Deny Refund",
};

function flattenValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function OutputValue({ value }: { value: string }) {
  const upper = value.toUpperCase();
  if (upper === "APPROVED" || upper === "TRUE" || upper === "YES")
    return <span className="text-success font-semibold">{value}</span>;
  if (upper === "DENIED" || upper === "FALSE" || upper === "NO")
    return <span className="text-danger font-semibold">{value}</span>;
  if (upper === "PENDING")
    return <span className="text-warning font-semibold">{value}</span>;
  return <span className="text-text-col-secondary">{value}</span>;
}

function KeyValueTable({ data, depth = 0 }: { data: Record<string, unknown>; depth?: number }) {
  return (
    <dl className="space-y-1.5">
      {Object.entries(data).map(([k, v]) => {
        if (typeof v === "object" && v !== null && !Array.isArray(v)) {
          return (
            <div key={k}>
              <dt className="text-[10px] font-mono font-bold text-text-col-tertiary uppercase tracking-widest mt-2 mb-1">{k}</dt>
              <div className={`pl-3 border-l border-border-col ${depth > 0 ? "ml-2" : ""}`}>
                <KeyValueTable data={v as Record<string, unknown>} depth={depth + 1} />
              </div>
            </div>
          );
        }
        const displayVal = flattenValue(v);
        return (
          <div key={k} className="flex gap-3 items-baseline min-w-0">
            <dt className="text-[10px] font-mono text-text-col-tertiary shrink-0 w-28 truncate capitalize">
              {k.replace(/_/g, " ")}
            </dt>
            <dd className="text-xs font-mono min-w-0 break-all">
              <OutputValue value={displayVal} />
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

function inputSummary(input: Record<string, unknown>): string {
  return Object.entries(input)
    .map(([k, v]) => `${k.replace(/_/g, "_")}: ${flattenValue(v)}`)
    .join("  ·  ");
}

function outputSummary(output: unknown): string {
  if (!output || typeof output !== "object") return flattenValue(output);
  const obj = output as Record<string, unknown>;
  if ("status" in obj) return String(obj.status);
  if ("found" in obj) return obj.found ? "Found" : "Not found";
  if ("error" in obj) return String(obj.error);
  return "See details";
}

interface EntryRowProps {
  entry: LogEntry;
  isLast: boolean;
  isFirstOfTool: boolean;
}

function EntryRow({ entry, isLast, isFirstOfTool }: EntryRowProps) {
  const [open, setOpen] = useState(isLast);
  const isCall = entry.step.startsWith("Calling");
  const time = new Date(entry.timestamp).toLocaleTimeString([], {
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });

  const colors = TOOL_COLOR[entry.tool] ?? {
    badge: "border-border-col text-text-col-tertiary bg-background-raised",
    line: "bg-border-col",
  };
  const label = TOOL_LABEL[entry.tool] ?? entry.tool.replace(/_/g, " ");

  const outputObj =
    entry.output && typeof entry.output === "object"
      ? (entry.output as Record<string, unknown>)
      : null;
  const hasError = outputObj && ("error" in outputObj || outputObj.found === false);

  return (
    <div className={`relative pl-5 ${isLast ? "" : "pb-1"}`}>
      {/* Timeline line */}
      <div className={`absolute left-[7px] top-0 ${isLast ? "h-4" : "h-full"} w-px ${colors.line} opacity-30`} />
      {/* Timeline dot */}
      <div className={`absolute left-[3px] top-4 w-2 h-2 rounded-full border-2 ${
        isCall
          ? "border-background-base bg-accent"
          : hasError
            ? "border-background-base bg-danger"
            : "border-background-base bg-success"
      }`} />

      <div className="border border-border-col rounded overflow-hidden mb-1.5">
        <button
          onClick={() => setOpen((v) => !v)}
          className="w-full flex items-center gap-2 px-3 py-2.5 bg-background-surface hover:bg-background-raised text-left transition-colors duration-150 min-w-0"
        >
          {/* CALL / RESULT badge */}
          <span className={`shrink-0 text-[9px] font-mono font-bold px-1.5 py-0.5 rounded uppercase tracking-wider border ${
            isCall
              ? "bg-accent/10 text-accent border-accent/30"
              : hasError
                ? "bg-danger/10 text-danger border-danger/30"
                : "bg-success/10 text-success border-success/30"
          }`}>
            {isCall ? "call" : hasError ? "err" : "done"}
          </span>

          {/* Tool name */}
          <span className={`shrink-0 text-xs font-mono font-semibold px-2 py-0.5 rounded border ${colors.badge}`}>
            {label}
          </span>

          {/* Inline summary */}
          <span className="flex-1 text-[11px] text-text-col-tertiary font-mono truncate min-w-0">
            {isCall
              ? inputSummary(entry.input)
              : outputSummary(entry.output)}
          </span>

          <span className="shrink-0 text-[10px] text-text-col-tertiary font-mono">{time}</span>
          <span className="shrink-0 text-text-col-tertiary text-[10px]">{open ? "▲" : "▼"}</span>
        </button>

        {open && (
          <div className="border-t border-border-col bg-background-base divide-y divide-border-col/50">
            {isCall && Object.keys(entry.input).length > 0 && (
              <div className="px-4 py-3">
                <p className="text-[9px] font-mono font-bold text-text-col-tertiary uppercase tracking-widest mb-2">
                  Parameters
                </p>
                <KeyValueTable data={entry.input} />
              </div>
            )}
            {!isCall && entry.output !== null && entry.output !== undefined && (
              <div className="px-4 py-3">
                <p className="text-[9px] font-mono font-bold text-text-col-tertiary uppercase tracking-widest mb-2">
                  Result
                </p>
                {outputObj ? (
                  <KeyValueTable data={outputObj} />
                ) : (
                  <span className="text-xs font-mono text-text-col-secondary">{String(entry.output)}</span>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default function ReasoningLog({ entries }: { entries: LogEntry[] }) {
  if (entries.length === 0) {
    return (
      <p className="text-sm text-text-col-tertiary font-mono italic text-center py-8">
        Agent reasoning steps will appear here…
      </p>
    );
  }

  return (
    <div className="pt-1">
      {entries.map((entry, i) => {
        const prev = entries[i - 1];
        const isFirstOfTool = !prev || prev.tool !== entry.tool;
        return (
          <EntryRow
            key={i}
            entry={entry}
            isLast={i === entries.length - 1}
            isFirstOfTool={isFirstOfTool}
          />
        );
      })}
    </div>
  );
}
