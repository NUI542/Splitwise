import { useCallback, useEffect, useState } from "react";
import { AssistantPanel } from "./AssistantPanel";
import { api } from "./api";
import { Notice } from "./components";
import { DealBuilder } from "./screens/DealBuilder";
import { Explain } from "./screens/Explain";
import { Sales } from "./screens/Sales";
import { Watch } from "./screens/Watch";
import type { DealListItem, Registry } from "./types";

type Tab = "deal" | "sales" | "explain" | "watch";

const TABS: { id: Tab; label: string }[] = [
  { id: "deal", label: "Deal" },
  { id: "sales", label: "Sales" },
  { id: "explain", label: "Explain" },
  { id: "watch", label: "Watch" },
];

export function App() {
  const [tab, setTab] = useState<Tab>("deal");
  const [registry, setRegistry] = useState<Registry | null>(null);
  const [deals, setDeals] = useState<DealListItem[]>([]);
  const [dealId, setDealId] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [target, setTarget] = useState<{ saleId: string; party: string } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const reloadRegistry = useCallback(() => {
    api.registry().then(setRegistry).catch(() => setProblem("Can't reach the API. Start it with: uvicorn api.main:create_app --factory"));
  }, []);
  useEffect(() => { reloadRegistry(); }, [reloadRegistry]);

  useEffect(() => { api.deals().then(setDeals).catch(() => undefined); }, [tick]);

  const changed = useCallback(() => setTick((t) => t + 1), []);

  async function reset() {
    if (!window.confirm("Wipe every deal, sale, flag and chain record?")) return;
    await api.sim("reset");
    setDealId(null); setTarget(null); changed(); reloadRegistry();
  }

  async function seed() {
    const r = await api.sim("seed-locked-deal").catch((e: Error) => { setProblem(e.message); return null; });
    if (r?.deal_id) setDealId(r.deal_id);
    changed();
  }

  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand">
            <div className="brand-mark" aria-hidden>E</div>
            <div>
              <h1>Edition Deal Agent</h1>
              <small>A BASIX.MARKET module · MeTTa rules on Hyperon · Track 02, challenge 6</small>
            </div>
          </div>
          <nav className="tabs" role="tablist">
            {TABS.map((t, i) => (
              <button key={t.id} role="tab" className="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}>
                <span className="step">{i + 1}</span>{t.label}
              </button>
            ))}
          </nav>
        </div>
      </header>
      <div className="banner">
        <div className="topbar-inner">
          Placeholder data: the artwork, people, shares and wallets are invented. Minting and money are simulated. Every decision on screen is made by the agent's MeTTa rules.
        </div>
      </div>

      <main className="main">
        {problem && <div style={{ marginBottom: 16 }}><Notice kind="error">{problem}</Notice></div>}
        {/* Every screen stays mounted so a half-written deal survives switching tabs. */}
        {registry && (
          <>
            <div hidden={tab !== "deal"}>
              <DealBuilder registry={registry} deals={deals} dealId={dealId} onSelectDeal={setDealId} onChanged={changed} onRegistryChanged={reloadRegistry} tick={tick} />
            </div>
            <div hidden={tab !== "sales"}>
              <Sales registry={registry} deals={deals} tick={tick} onChanged={changed}
                onExplain={(saleId, party) => { setTarget({ saleId, party }); setTab("explain"); }} />
            </div>
            <div hidden={tab !== "explain"}>
              <Explain target={target} onTarget={setTarget} tick={tick} />
            </div>
            <div hidden={tab !== "watch"}>
              <Watch registry={registry} tick={tick} onChanged={changed} />
            </div>
          </>
        )}
      </main>

      <AssistantPanel />

      <footer className="footer">
        <span>Demo controls:</span>
        <button className="small" onClick={seed}>Seed a locked sample deal</button>
        <button className="small danger" onClick={reset}>Reset everything</button>
        <span>API docs at <a href="/docs">/docs</a></span>
      </footer>
    </>
  );
}
