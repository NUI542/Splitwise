import { useEffect, useState } from "react";
import { api } from "../api";
import { Card, Notice, RuleTag, Spinner } from "../components";
import type { Explanation, Sale, StepRow } from "../types";

interface Props {
  target: { saleId: string; party: string } | null;
  onTarget: (t: { saleId: string; party: string }) => void;
  tick: number;
}

/** Which trace steps produced this party's line. */
function relevant(step: StepRow, party: string, role: string, artist: string | null): boolean {
  if (step.rule === "share-split") return step.party === party;
  if (step.rule === "seller-proceeds") return role === "seller";
  if (step.rule === "leftover-to-artist") return party === artist;
  return step.rule === "royalty-amount" || step.rule === "sum-check" || step.rule === "primary-split";
}

export function Explain({ target, onTarget, tick }: Props) {
  const [sales, setSales] = useState<Sale[]>([]);
  const [answer, setAnswer] = useState<Explanation | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => { api.sales().then(setSales).catch(() => undefined); }, [tick]);

  const sale = sales.find((s) => s.sale_id === target?.saleId) ?? null;

  useEffect(() => {
    if (!target) { setAnswer(null); return; }
    setLoading(true); setProblem(null);
    api.explain(target.saleId, target.party)
      .then(setAnswer)
      .catch((e: Error) => { setAnswer(null); setProblem(e.message); })
      .finally(() => setLoading(false));
  }, [target?.saleId, target?.party]);

  const line = answer?.lines[0];
  const artist = sale?.lines.find((l) => l.role === "artist")?.party ?? null;
  const [question, ...rest] = (answer?.explanation ?? "").split("\n");

  return (
    <div className="stack">
      <Card title="Ask why" actions={loading ? <Spinner /> : undefined}>
        <div className="fields">
          <label className="field"><span>Sale</span>
            <select value={target?.saleId ?? ""} onChange={(e) => {
              const s = sales.find((x) => x.sale_id === e.target.value);
              if (s) onTarget({ saleId: s.sale_id, party: s.lines[0].party });
            }}>
              <option value="" disabled>Choose a sale…</option>
              {[...sales].reverse().map((s) => (
                <option key={s.sale_id} value={s.sale_id}>{s.sale_id} · {s.type} of edition {s.edition} · {s.price_display}</option>
              ))}
            </select>
          </label>
          <label className="field"><span>Who received the money</span>
            <select value={target?.party ?? ""} disabled={!sale} onChange={(e) => target && onTarget({ ...target, party: e.target.value })}>
              {sale?.lines.map((l) => <option key={l.party} value={l.party}>{l.name} ({l.role}) · {l.amount_display}</option>)}
            </select>
          </label>
        </div>
        {sales.length === 0 && <p className="muted small" style={{ marginTop: 10 }}>No sales yet. Simulate one on the Sales screen.</p>}
      </Card>

      {problem && <Notice kind="error">{problem}</Notice>}

      {answer && line && (
        <>
          <Card title={<span className="question">{question}</span>}>
            <div className="stack">
              <div className="answer">{rest.join("\n")}</div>
              <p className="muted small">
                Written from the agent's trace for this payout (deal {answer.deal_id}, version {answer.deal_version}),
                so the numbers explained are the numbers paid.
              </p>
            </div>
          </Card>

          <Card title="Step by step: the agent's trace" tight>
            <div className="table-wrap">
              <table className="data">
                <thead><tr><th className="num">#</th><th>Rule</th><th>Inputs</th><th>Calculation</th><th className="num">Result</th></tr></thead>
                <tbody>
                  {answer.trace.steps.map((s, i) => (
                    <tr key={i} className={relevant(s, line.party, line.role, artist) ? "highlight" : ""}>
                      <td className="num">{i + 1}</td>
                      <td><RuleTag rule={s.rule} statement={s.statement} /><div className="muted small">{s.statement}</div></td>
                      <td className="small">{Object.entries(s.inputs).map(([k, v]) => <div key={k}><span className="muted">{k}:</span> {String(v)}</div>)}</td>
                      <td className="mono">{s.calculation}</td>
                      <td className="num">{s.result}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {sale && (
            <Card title={`Every line of ${sale.sale_id}`} tight>
              <div className="table-wrap">
                <table className="data">
                  <thead><tr><th>Received by</th><th>Role</th><th>Wallet</th><th className="num">Amount</th></tr></thead>
                  <tbody>
                    {sale.lines.map((l) => (
                      <tr key={l.party} className={`clickable ${l.party === line.party ? "highlight" : ""}`}
                        onClick={() => onTarget({ saleId: sale.sale_id, party: l.party })}>
                        <td>{l.name}</td><td>{l.role}</td><td className="mono">{l.wallet}</td><td className="num">{l.amount_display}</td>
                      </tr>
                    ))}
                    <tr><td colSpan={3}><strong>Total</strong> <span className="muted small">(equals the price paid)</span></td><td className="num"><strong>{sale.price_display}</strong></td></tr>
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
