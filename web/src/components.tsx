import type { ReactNode } from "react";
import type { Classification, FlagStatus, Report } from "./types";

export function RuleTag({ rule, statement }: { rule: string; statement?: string }) {
  return <code className="rule" title={statement}>{rule}</code>;
}

export function Card({ title, actions, children, tight }: {
  title: ReactNode; actions?: ReactNode; children: ReactNode; tight?: boolean;
}) {
  return (
    <section className="card">
      <header className="card-head">
        <h2>{title}</h2>
        {actions && <div className="row">{actions}</div>}
      </header>
      <div className={tight ? "card-body tight" : "card-body"}>{children}</div>
    </section>
  );
}

/** The agent's errors and warnings, each with the rule behind it. */
export function Findings({ report, emptyText }: { report: Report; emptyText?: string }) {
  const all = [...report.errors, ...report.warnings];
  if (all.length === 0) {
    return emptyText ? <p className="muted small">{emptyText}</p> : null;
  }
  return (
    <ul className="findings">
      {all.map((f, i) => (
        <li key={`${f.rule}-${i}`} className={`finding ${f.severity}`}>
          <div className="row spread">
            <span className="detail">{f.detail}</span>
            <RuleTag rule={f.rule} statement={f.statement} />
          </div>
          <div className="because">
            {f.severity === "error" ? "Rule" : "Warning"} on {f.field_label}: {f.statement}
          </div>
        </li>
      ))}
    </ul>
  );
}

export function Verdict({ report }: { report: Report }) {
  if (!report.valid) {
    const n = report.errors.length;
    return <span className="status bad">✕ {n} {n === 1 ? "error" : "errors"}</span>;
  }
  if (report.warnings.length) {
    return <span className="status warn">✓ Valid, {report.warnings.length} warning{report.warnings.length > 1 ? "s" : ""}</span>;
  }
  return <span className="status ok">✓ Every rule holds</span>;
}

export function Facts({ facts }: { facts: string[] }) {
  return (
    <details className="facts">
      <summary>The {facts.length} facts the agent reasoned over (MeTTa)</summary>
      <pre>{facts.join("\n")}</pre>
    </details>
  );
}

export function ClassBadge({ value }: { value: Classification }) {
  return <span className={`badge ${value}`}>{value}</span>;
}

export function StatusBadge({ value }: { value: FlagStatus }) {
  return <span className={`badge ${value}`}>{value}</span>;
}

export function Notice({ kind = "info", children }: { kind?: "info" | "error" | "ok"; children: ReactNode }) {
  return <div className={`notice ${kind === "info" ? "" : kind}`}>{children}</div>;
}

export function Spinner() {
  return <span className="spinner" aria-label="Working" />;
}

export function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium" });
}

export function short(text: string, n = 10): string {
  return text.length > n ? `${text.slice(0, n)}…` : text;
}
