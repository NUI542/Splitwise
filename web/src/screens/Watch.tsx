import { useEffect, useState } from "react";
import { api, nameOf } from "../api";
import { Card, ClassBadge, Notice, RuleTag, Spinner, StatusBadge, when } from "../components";
import type { Flag, FlagStatus, Registry, WatchRow } from "../types";

interface Props {
  registry: Registry;
  tick: number;
  onChanged: () => void;
}

const EVIDENCE_LABELS: Record<string, string> = {
  "from": "From",
  "to": "To",
  "buyer-paid-minor": "New holder paid in the transaction",
  "royalty-due-minor": "Royalty due on that price",
  "royalty-received-minor": "Royalty the co-owners received",
  "ledger-event": "BASIX.MARKET ledger entry",
};

export function Watch({ registry, tick, onChanged }: Props) {
  const [rows, setRows] = useState<WatchRow[] | null>(null);
  const [flags, setFlags] = useState<Flag[]>([]);
  const [filter, setFilter] = useState<FlagStatus | "ALL">("OPEN");
  const [scanning, setScanning] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const loadFlags = () => api.flags().then(setFlags).catch((e: Error) => setProblem(e.message));
  useEffect(() => { loadFlags(); }, [tick]);

  async function scan() {
    setScanning(true); setProblem(null);
    try {
      setRows(await api.scan());
      await loadFlags();
      onChanged();
    } catch (e) {
      setProblem((e as Error).message);
    } finally {
      setScanning(false);
    }
  }

  const shown = flags.filter((f) => filter === "ALL" || f.status === filter);

  return (
    <div className="stack">
      <Card title="Every transfer on the chain" actions={
        <button className="primary" disabled={scanning} onClick={scan}>{scanning ? <><Spinner /> Scanning…</> : "Scan the chain"}</button>}
        tight>
        {problem && <div className="card-body"><Notice kind="error">{problem}</Notice></div>}
        {rows === null ? (
          <div className="empty">Scan to have the agent classify every transfer. A transfer is not proof of a sale: it only says a royalty is missing when the same transaction shows a payment.</div>
        ) : rows.length === 0 ? <div className="empty">Nothing on the chain yet.</div> : (
          <div className="table-wrap">
            <table className="data">
              <thead><tr><th className="num">#</th><th>Transaction</th><th className="num">Edition</th><th>From → to</th><th>Classification</th><th>Because</th><th className="num">Owed</th><th>Flag</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.tx}>
                    <td className="num">{r.seq}</td>
                    <td className="mono">{r.tx}<div className="muted small">{when(r.at)}</div></td>
                    <td className="num">{r.edition}</td>
                    <td className="small">{nameOf(registry, String(r.evidence.from))} → {nameOf(registry, String(r.evidence.to))}</td>
                    <td><ClassBadge value={r.classification} /></td>
                    <td className="small"><RuleTag rule={r.rule} statement={r.statement} /><div className="muted">{r.statement}</div></td>
                    <td className="num">{r.total_owed_display ?? "—"}</td>
                    <td>{r.status ? <StatusBadge value={r.status} /> : <span className="muted small">none</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Flags" actions={
        <div className="row small">
          {(["OPEN", "RESOLVED", "DISMISSED", "ALL"] as const).map((s) => (
            <button key={s} className={filter === s ? "primary small" : "small"} onClick={() => setFilter(s)}>
              {s.toLowerCase()} ({s === "ALL" ? flags.length : flags.filter((f) => f.status === s).length})
            </button>
          ))}
        </div>}>
        {shown.length === 0 ? <div className="empty">No {filter === "ALL" ? "" : filter.toLowerCase()} flags.</div> : (
          <div className="stack">
            {shown.map((f) => <FlagCard key={f.flag_id} flag={f} registry={registry} onSaved={() => { loadFlags(); onChanged(); }} />)}
          </div>
        )}
      </Card>
    </div>
  );
}

function FlagCard({ flag, registry, onSaved }: { flag: Flag; registry: Registry; onSaved: () => void }) {
  const [reason, setReason] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function set(status: FlagStatus) {
    setBusy(true); setProblem(null);
    try {
      await api.updateFlag(flag.flag_id, status, reason);
      setReason("");
      onSaved();
    } catch (e) {
      setProblem((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className={`flag ${flag.status}`}>
      <div className="row spread">
        <div className="row">
          <ClassBadge value={flag.classification} />
          <span className="mono">{flag.tx}</span>
          <span className="muted small">edition {flag.edition} · {flag.deal_id}{flag.deal_version ? ` v${flag.deal_version}` : ""}</span>
        </div>
        <StatusBadge value={flag.status} />
      </div>
      <p>{flag.explanation}</p>
      <p className="small"><RuleTag rule={flag.rule} statement={flag.statement} /> <span className="muted">{flag.statement}</span></p>

      {flag.owed.length > 0 && (
        <div className="table-wrap">
          <table className="data">
            <thead><tr><th>Co-owner</th><th className="num">Due</th><th className="num">Received</th><th className="num">Owed</th></tr></thead>
            <tbody>
              {flag.owed.map((o) => (
                <tr key={o.party}>
                  <td>{o.name}</td>
                  <td className="num">{o.due_display}</td>
                  <td className="num">{o.received_display}</td>
                  <td className="num"><strong>{o.amount_display}</strong></td>
                </tr>
              ))}
              <tr><td colSpan={3}><strong>Total owed</strong></td><td className="num"><strong>{flag.total_owed_display}</strong></td></tr>
            </tbody>
          </table>
        </div>
      )}

      <details>
        <summary className="muted small">Evidence and the agent's calculation</summary>
        <div className="stack" style={{ marginTop: 8 }}>
          <dl className="kv">
            {Object.entries(flag.evidence).map(([k, v]) => (
              <FragmentKV key={k} label={EVIDENCE_LABELS[k] ?? k}
                value={flag.evidence_display[k] ?? (k === "from" || k === "to" ? `${nameOf(registry, String(v))} (${v})` : v === null ? "none" : String(v))} />
            ))}
          </dl>
          {flag.steps.length > 0 && (
            <table className="data">
              <tbody>
                {flag.steps.map((s, i) => (
                  <tr key={i}><td><RuleTag rule={s.rule} statement={s.statement} /></td><td className="mono">{s.calculation}</td><td className="num">{s.result}</td></tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </details>

      <ul className="history">
        {flag.history.map((h, i) => <li key={i}>{when(h.at)} · <strong>{h.status}</strong> · {h.reason}</li>)}
      </ul>

      <div className="row">
        <input style={{ flex: 1, minWidth: 220 }} placeholder="Reason (required, kept in the history)" value={reason} onChange={(e) => setReason(e.target.value)} />
        {flag.status !== "RESOLVED" && <button className="small" disabled={busy || !reason.trim()} onClick={() => set("RESOLVED")}>Resolve</button>}
        {flag.status !== "DISMISSED" && <button className="small" disabled={busy || !reason.trim()} onClick={() => set("DISMISSED")}>Dismiss</button>}
        {flag.status !== "OPEN" && <button className="small" disabled={busy || !reason.trim()} onClick={() => set("OPEN")}>Reopen</button>}
      </div>
      {problem && <Notice kind="error">{problem}</Notice>}
    </article>
  );
}

function FragmentKV({ label, value }: { label: string; value: string }) {
  return <><dt>{label}</dt><dd>{value}</dd></>;
}
