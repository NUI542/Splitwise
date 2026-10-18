import { useEffect, useState } from "react";
import { ApiError, api, nameOf, type ChainView } from "../api";
import { Card, Findings, Notice, Spinner, when } from "../components";
import type { DealListItem, Registry, Report, Sale } from "../types";

interface Props {
  registry: Registry;
  deals: DealListItem[];
  tick: number;
  onChanged: () => void;
  onExplain: (saleId: string, party: string) => void;
}

const ACTIONS = [
  { scenario: "primary-sale", label: "Primary sale", hint: "Sold on BASIX.MARKET at the deal price" },
  { scenario: "resale-with-royalty", label: "Resale with royalty", hint: "Resold on BASIX.MARKET; the royalty is paid out" },
  { scenario: "resale-without-royalty", label: "Resale without royalty", hint: "Resold elsewhere; the buyer pays the seller in full" },
  { scenario: "gift-transfer", label: "Gift transfer", hint: "Moved to another wallet with no payment" },
];

export function Sales({ registry, deals, tick, onChanged, onExplain }: Props) {
  const locked = deals.filter((d) => d.active_version !== null);
  const [dealId, setDealId] = useState<string>("");
  const [edition, setEdition] = useState("");
  const [price, setPrice] = useState("");
  const [buyer, setBuyer] = useState("");
  const [partial, setPartial] = useState({ party: "artist-a", amount: "" });
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [refusal, setRefusal] = useState<{ message: string; report?: Report } | null>(null);
  const [sales, setSales] = useState<Sale[]>([]);
  const [chain, setChain] = useState<ChainView | null>(null);

  const active = dealId || locked[locked.length - 1]?.deal_id || "";
  const collectors = registry.parties.filter((p) => p.kind === "collector");
  const coOwners = registry.parties.filter((p) => p.kind === "co-owner");

  useEffect(() => {
    if (!active) return;
    api.sales(active).then(setSales).catch(() => undefined);
    api.chain(active).then(setChain).catch(() => undefined);
  }, [active, tick]);

  async function simulate(scenario: string, extra: Record<string, unknown> = {}) {
    setBusy(scenario); setNote(null); setRefusal(null);
    const params: Record<string, unknown> = { deal_id: active, ...extra };
    if (edition.trim()) params.edition = edition.trim();
    if (price.trim()) params.price = price.trim();
    if (buyer) params.buyer = buyer;
    try {
      const r = await api.sim(scenario, params);
      const where = r.sale ? `Ledger entry ${r.sale.sale_id}, ${r.sale.tx}.` : `Chain only: ${r.transfer?.tx}. The ledger doesn't know about it; the Watch screen will.`;
      setNote(`${r.note} ${where}`);
      onChanged();
    } catch (e) {
      setRefusal({ message: (e as Error).message, report: e instanceof ApiError ? e.report : undefined });
    } finally {
      setBusy(null);
    }
  }

  if (locked.length === 0) {
    return <Card title="Sales"><div className="empty">Lock a deal on the Deal screen first. Sales only happen under a locked deal.</div></Card>;
  }

  const ledgerTx = new Set(sales.map((s) => s.tx));

  return (
    <div className="stack">
      <Card title="Simulate" actions={
        <label className="row small">Deal
          <select value={active} onChange={(e) => setDealId(e.target.value)}>
            {locked.map((d) => <option key={d.deal_id} value={d.deal_id}>{d.deal_id} (v{d.active_version})</option>)}
          </select>
        </label>}>
        <div className="stack">
          <div className="fields">
            <label className="field"><span>Edition (optional)</span><input inputMode="numeric" value={edition} onChange={(e) => setEdition(e.target.value)} placeholder="next / first held" /></label>
            <label className="field"><span>Price, KES (optional)</span><input inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} placeholder="scenario default" /></label>
            <label className="field"><span>Buyer (optional)</span>
              <select value={buyer} onChange={(e) => setBuyer(e.target.value)}>
                <option value="">Next collector</option>
                {collectors.map((c) => <option key={c.id} value={c.wallets[0]}>{c.name}</option>)}
              </select>
            </label>
          </div>
          <div className="sim-buttons">
            {ACTIONS.map((a) => (
              <button key={a.scenario} disabled={busy !== null} onClick={() => simulate(a.scenario)}>
                {busy === a.scenario ? <Spinner /> : null} {a.label}<small>{a.hint}</small>
              </button>
            ))}
          </div>
          <details>
            <summary className="muted small">Resale elsewhere with part of the royalty paid</summary>
            <div className="row" style={{ marginTop: 8 }}>
              <select value={partial.party} onChange={(e) => setPartial({ ...partial, party: e.target.value })}>
                {coOwners.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
              <input inputMode="decimal" placeholder="KES paid" value={partial.amount} onChange={(e) => setPartial({ ...partial, amount: e.target.value })} />
              <button disabled={busy !== null || !partial.amount.trim()}
                onClick={() => simulate("resale-partial-royalty", { paid: [{ party: partial.party, amount: partial.amount.trim() }] })}>
                Simulate
              </button>
            </div>
          </details>
          {note && <Notice kind="ok">{note}</Notice>}
          {refusal && (
            <div className="stack">
              <Notice kind="error">{refusal.message}</Notice>
              {refusal.report && <Findings report={refusal.report} />}
            </div>
          )}
        </div>
      </Card>

      <Card title="Ledger: sales paid out by the agent" tight>
        {sales.length === 0 ? <div className="empty">No sales yet.</div> : (
          <div className="table-wrap">
            <table className="data">
              <thead><tr><th>Sale</th><th>When</th><th>Type</th><th className="num">Edition</th><th className="num">Price</th><th>From → to</th><th>Deal</th><th>Payout lines (click one to ask why)</th></tr></thead>
              <tbody>
                {[...sales].reverse().map((s) => (
                  <tr key={s.sale_id}>
                    <td className="mono">{s.sale_id}<div className="muted small">{s.tx}</div></td>
                    <td className="small">{when(s.sale_at)}</td>
                    <td>{s.type}</td>
                    <td className="num">{s.edition}</td>
                    <td className="num">{s.price_display}</td>
                    <td className="small">{s.seller_name} → {s.buyer_name}</td>
                    <td className="small">v{s.deal_version}</td>
                    <td>
                      <table className="lines">
                        <tbody>
                          {s.lines.map((l) => (
                            <tr key={l.party} className="clickable" onClick={() => onExplain(s.sale_id, l.party)} title="Why did they get this?">
                              <td>{l.name}<span className="muted small"> · {l.role}</span></td>
                              <td className="num">{l.amount_display}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="On the chain (simulated)" tight>
        {!chain || chain.transfers.length === 0 ? <div className="empty">Nothing on the chain yet.</div> : (
          <div className="table-wrap">
            <table className="data">
              <thead><tr><th className="num">#</th><th>Transaction</th><th className="num">Edition</th><th>From → to</th><th className="num">Paid inside it</th><th>In the ledger?</th></tr></thead>
              <tbody>
                {[...chain.transfers].reverse().map((t) => (
                  <tr key={t.tx}>
                      <td className="num">{t.seq}</td>
                      <td className="mono">{t.tx}</td>
                      <td className="num">{t.edition}</td>
                      <td className="small">{nameOf(registry, t.from_wallet)} → {nameOf(registry, t.to_wallet)}</td>
                      <td className="num">{t.paid_display ?? <span className="muted">nothing</span>}</td>
                      <td className="small">{ledgerTx.has(t.tx) ? "yes, a BASIX.MARKET sale" : <span className="muted">no, happened elsewhere</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
