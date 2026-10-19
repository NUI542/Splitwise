import { useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "../api";
import { Card, Facts, Findings, Notice, RuleTag, Spinner, Verdict, short, when } from "../components";
import type { CheckReport, DealListItem, Draft, Registry, RegistryArtwork, Report, VersionView } from "../types";

interface Row {
  key: string;
  id: string;
  name: string;
  role: "artist" | "co-owner";
  wallet: string;
  kind: "percent" | "fixed";
  share: string;
}

interface Form {
  artwork_id: string;
  currency: string;
  edition_count: string;
  price: string;
  royalty_percent: string;
  rows: Row[];
}

let rowSeq = 0;
const newKey = () => `row-${++rowSeq}`;

const EMPTY: Form = {
  artwork_id: "", currency: "KES", edition_count: "", price: "", royalty_percent: "",
  rows: [{ key: newKey(), id: "", name: "", role: "artist", wallet: "", kind: "percent", share: "" }],
};

function toDraft(f: Form): Draft {
  return {
    artwork_id: f.artwork_id || null,
    currency: f.currency || null,
    edition_count: f.edition_count,
    price: f.price,
    royalty_percent: f.royalty_percent,
    parties: f.rows.map((r) => ({ id: r.id.trim(), name: r.name.trim(), role: r.role, wallet: r.wallet.trim() || null })),
    shares: f.rows
      .filter((r) => r.share.trim() !== "")
      .map((r) => ({ party_id: r.id.trim(), kind: r.kind, value: r.share.trim() })),
  };
}

function fromDraft(d: Draft): Form {
  return {
    artwork_id: d.artwork_id ?? "",
    currency: d.currency ?? "KES",
    edition_count: d.edition_count == null ? "" : String(d.edition_count),
    price: d.price == null ? "" : String(d.price),
    royalty_percent: d.royalty_percent == null ? "" : String(d.royalty_percent),
    rows: d.parties.map((p) => {
      const s = d.shares.find((x) => x.party_id === p.id);
      return {
        key: newKey(), id: p.id, name: p.name, role: p.role === "artist" ? "artist" : "co-owner",
        wallet: p.wallet ?? "", kind: s?.kind === "fixed" ? "fixed" : "percent",
        share: s?.value == null ? "" : String(s.value),
      };
    }),
  };
}

interface Props {
  registry: Registry;
  deals: DealListItem[];
  dealId: string | null;
  onSelectDeal: (id: string | null) => void;
  onChanged: () => void;
  onRegistryChanged: () => void;
  tick: number; // bumps whenever data changes elsewhere
}

const DEFAULT_ARTWORK = "aw-placeholder-001";
const ADD_ARTWORK = "__add__";

export function DealBuilder({ registry, deals, dealId, onSelectDeal, onChanged, onRegistryChanged, tick }: Props) {
  const [form, setForm] = useState<Form>(EMPTY);
  const [baseDeal, setBaseDeal] = useState<string | null>(null); // the deal a new version is for
  const [report, setReport] = useState<CheckReport | null>(null);
  const [checking, setChecking] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [adding, setAdding] = useState(false); // the "add a synthetic artwork" form is open
  // The terms last saved (or loaded from a version): saving them again would change nothing.
  const [savedAs, setSavedAs] = useState<{ hash: string; version: number } | null>(null);
  const seq = useRef(0);

  // Live check: every change goes to the agent (debounced); stale answers are dropped.
  useEffect(() => {
    const mine = ++seq.current;
    setChecking(true);
    const timer = window.setTimeout(() => {
      api.check(toDraft(form), baseDeal)
        .then((r) => { if (mine === seq.current) { setReport(r); setProblem(null); } })
        .catch((e: Error) => { if (mine === seq.current) setProblem(e.message); })
        .finally(() => { if (mine === seq.current) setChecking(false); });
    }, 450);
    return () => window.clearTimeout(timer);
  }, [form, baseDeal]);

  const coOwners = registry.parties.filter((p) => p.kind === "co-owner");
  const artwork = registry.artworks.find((a) => a.id === form.artwork_id);

  const fieldState = useMemo(() => {
    const err = new Set<string>(), warn = new Set<string>();
    const partyErr = new Set<string>(), shareErr = new Set<string>();
    let shareAll = false; // a rule about the shares as a whole, such as "add up to 100%"
    for (const f of report?.errors ?? []) {
      err.add(f.field);
      const who = f.data.party as string | undefined;
      if (who !== undefined && f.field === "shares") shareErr.add(who);
      if (who !== undefined && f.field === "parties") partyErr.add(who);
      if (who === undefined && f.field === "shares") shareAll = true;
    }
    for (const f of report?.warnings ?? []) warn.add(f.field);
    return { err, warn, partyErr, shareErr, shareAll };
  }, [report]);

  const cls = (field: string) =>
    fieldState.err.has(field) ? "field has-error" : fieldState.warn.has(field) ? "field has-warning" : "field";

  const set = <K extends keyof Form>(key: K, value: Form[K]) => setForm((f) => ({ ...f, [key]: value }));
  const setRow = (key: string, patch: Partial<Row>) =>
    setForm((f) => ({ ...f, rows: f.rows.map((r) => (r.key === key ? { ...r, ...patch } : r)) }));

  function pickParty(key: string, id: string) {
    const known = registry.parties.find((p) => p.id === id);
    setRow(key, known ? { id, name: known.name, wallet: known.wallets[0] ?? "" } : { id });
  }

  function load(draft: Draft, forDeal: string | null, note: string, saved: { hash: string; version: number } | null = null) {
    setForm(fromDraft(draft));
    setBaseDeal(forDeal);
    setMessage(note);
    setSavedAs(saved);
  }

  /** The valid or broken example, written by the API for the chosen artwork. */
  async function loadExample(kind: "valid" | "invalid") {
    const artworkId = form.artwork_id || DEFAULT_ARTWORK;
    const title = registry.artworks.find((a) => a.id === artworkId)?.title ?? artworkId;
    try {
      const examples = await api.samples(artworkId);
      load(examples[kind], null, kind === "valid"
        ? `Loaded the valid example for ${title}.`
        : `Loaded the broken example for ${title}: shares total 110% and the royalty is 12%.`);
    } catch (e) {
      setProblem((e as Error).message);
    }
  }

  async function save() {
    setMessage(null);
    try {
      const saved = await api.saveVersion(toDraft(form), baseDeal);
      setBaseDeal(saved.deal_id);
      if (report) setSavedAs({ hash: report.terms_hash, version: saved.version });
      onSelectDeal(saved.deal_id);
      onChanged();
      setMessage(saved.unchanged
        ? `Nothing changed since ${saved.deal_id} version ${saved.version}, so no new version was made.`
        : `Saved as ${saved.deal_id} version ${saved.version}. Every co-owner now approves it below.`);
    } catch (e) {
      setProblem((e as Error).message);
    }
  }

  return (
    <div className="grid-2">
      <div className="stack">
        <Card
          title={baseDeal ? `New version of ${baseDeal}` : "New deal"}
          actions={<>
            <button className="small" title="Written for the chosen artwork" onClick={() => loadExample("invalid")}>Load broken example</button>
            <button className="small" title="Written for the chosen artwork" onClick={() => loadExample("valid")}>Load valid example</button>
            <button className="small" onClick={() => load(toDraft(EMPTY), null, "Started a blank deal.")}>Clear</button>
          </>}
        >
          <div className="stack">
            {message && <Notice>{message}</Notice>}
            <div className="fields">
              <label className={`${cls("artwork_id")} wide`}>
                <span>Artwork</span>
                <select value={form.artwork_id} onChange={(e) => {
                  if (e.target.value === ADD_ARTWORK) setAdding(true);
                  else set("artwork_id", e.target.value);
                }}>
                  <option value="">Choose…</option>
                  {registry.artworks.map((a) => <option key={a.id} value={a.id}>{a.title}</option>)}
                  <option value={ADD_ARTWORK}>+ Add a synthetic artwork…</option>
                </select>
              </label>
              <label className={cls("currency")}>
                <span>Currency</span>
                <input value={form.currency} onChange={(e) => set("currency", e.target.value.toUpperCase())} />
              </label>
              <label className={cls("edition_count")}>
                <span>Editions</span>
                <input inputMode="numeric" value={form.edition_count} onChange={(e) => set("edition_count", e.target.value)} />
              </label>
              <label className={cls("price")}>
                <span>Price ({form.currency || "KES"})</span>
                <input inputMode="decimal" value={form.price} onChange={(e) => set("price", e.target.value)} placeholder="15000.00" />
              </label>
              <label className={cls("royalty")}>
                <span>Resale royalty %</span>
                <input inputMode="decimal" value={form.royalty_percent} onChange={(e) => set("royalty_percent", e.target.value)} placeholder="10" />
              </label>
            </div>
            {artwork && (
              <p className="muted small">
                Rights holder: <strong>{registry.parties.find((p) => p.id === artwork.rights_holder)?.name ?? artwork.rights_holder}</strong>
                {" · "}consented to up to <strong>{artwork.consented_editions}</strong> editions.
                {" "}The example buttons write their deals for this artwork.
              </p>
            )}
            {adding && (
              <AddArtwork registry={registry} onCancel={() => setAdding(false)}
                onAdded={(art) => {
                  setAdding(false);
                  onRegistryChanged();
                  set("artwork_id", art.id);
                  setMessage(`Added ${art.title}. Load its valid or broken example, or write a deal for it.`);
                }} />
            )}

            <div>
              <div className="row spread">
                <h3>Co-owners and shares</h3>
                <button className="small" onClick={() => setForm((f) => ({ ...f, rows: [...f.rows, { key: newKey(), id: "", name: "", role: "co-owner", wallet: "", kind: "percent", share: "" }] }))}>
                  + Add co-owner
                </button>
              </div>
              <datalist id="party-ids">
                {coOwners.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </datalist>
              <div className="owners">
                {form.rows.map((r, i) => {
                  const bad = fieldState.partyErr.has(r.id) ? "has-error" : "";
                  const badShare = fieldState.shareAll || fieldState.shareErr.has(r.id) ? "has-error" : "";
                  return (
                    <div key={r.key} className={`owner ${r.role === "artist" ? "is-artist" : ""}`}>
                      <label className="field o-name"><span>Co-owner {i + 1}</span>
                        <input className={bad} value={r.name} onChange={(e) => setRow(r.key, { name: e.target.value })} placeholder="Name" />
                      </label>
                      <label className="field o-id"><span>ID</span>
                        <input className={bad} list="party-ids" value={r.id} onChange={(e) => pickParty(r.key, e.target.value)} placeholder="party-id" />
                      </label>
                      <label className="o-artist">
                        <input type="checkbox" checked={r.role === "artist"}
                          onChange={(e) => setRow(r.key, { role: e.target.checked ? "artist" : "co-owner" })} /> Artist
                      </label>
                      <button className="link danger o-remove" aria-label={`Remove co-owner ${i + 1}`}
                        onClick={() => setForm((f) => ({ ...f, rows: f.rows.filter((x) => x.key !== r.key) }))}>Remove</button>
                      <label className="field o-wallet"><span>Payout wallet</span>
                        <input className={bad} value={r.wallet} onChange={(e) => setRow(r.key, { wallet: e.target.value })} />
                      </label>
                      <label className="field o-share"><span>Share</span>
                        <div className="share-input">
                          <input className={badShare} inputMode="decimal" value={r.share}
                            onChange={(e) => setRow(r.key, { share: e.target.value })} />
                          <select value={r.kind} aria-label="Share kind" onChange={(e) => setRow(r.key, { kind: e.target.value as Row["kind"] })}>
                            <option value="percent">%</option>
                            <option value="fixed">{form.currency || "KES"}</option>
                          </select>
                        </div>
                      </label>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </Card>

        {dealId && (
          <Versions dealId={dealId} tick={tick} onChanged={onChanged}
            onEdit={(v) => load(v.draft, dealId, `Editing a new version of ${dealId}, starting from version ${v.version}. Saving it needs every co-owner to approve again.`,
              { hash: v.terms_hash, version: v.version })} />
        )}
      </div>

      <div className="stack sticky">
        <Card title="The agent's check" actions={<>{checking && <Spinner />}{report && <Verdict report={report} />}</>}>
          <div className="stack">
            {problem && <Notice kind="error">{problem}</Notice>}
            {report && <Findings report={report} emptyText="Every rule holds for these terms." />}
            {report?.summary && (
              <div className="stack">
                <h3>In plain words</h3>
                <ul className="summary-text">{report.summary.text.map((t) => <li key={t}>{t}</li>)}</ul>
                <div className="table-wrap">
                  <table className="data">
                    <thead><tr><th>Co-owner</th><th className="num">Share</th><th className="num">Per primary sale</th></tr></thead>
                    <tbody>
                      {report.summary.lines.map((l) => (
                        <tr key={l.party}>
                          <td>{l.name}{l.role === "artist" && <span className="muted small"> · artist</span>}</td>
                          <td className="num">{l.share_display}</td>
                          <td className="num">{l.amount_display}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
            {report && <Facts facts={report.facts} />}
            <div className="row">
              {savedAs && report?.terms_hash === savedAs.hash ? (
                <span className="status ok">✓ These terms are {baseDeal} version {savedAs.version}. Change a term to make a new version.</span>
              ) : (
                <>
                  <button className="primary" disabled={!report?.valid || checking} onClick={save}>
                    {baseDeal ? `Save as version ${report?.version ?? ""} of ${baseDeal}` : "Save deal for approval"}
                  </button>
                  {!report?.valid && <span className="muted small">Fix the errors to save.</span>}
                </>
              )}
            </div>
          </div>
        </Card>
        {deals.length > 0 && (
          <Card title="Deals">
            <div className="row">
              {deals.map((d) => (
                <button key={d.deal_id} className={d.deal_id === dealId ? "primary small" : "small"} onClick={() => onSelectDeal(d.deal_id)}>
                  {d.deal_id} · v{d.latest_version}{d.active_version ? ` (v${d.active_version} active)` : ""}
                </button>
              ))}
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}

function Versions({ dealId, tick, onChanged, onEdit }: {
  dealId: string; tick: number; onChanged: () => void; onEdit: (v: VersionView) => void;
}) {
  const [versions, setVersions] = useState<VersionView[]>([]);
  const [lockReport, setLockReport] = useState<Report | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = () => api.versions(dealId).then(setVersions).catch((e: Error) => setProblem(e.message));
  useEffect(() => { setLockReport(null); setProblem(null); }, [dealId]);
  useEffect(() => { refresh(); }, [dealId, tick]);

  async function act(fn: () => Promise<unknown>) {
    setBusy(true); setProblem(null); setLockReport(null);
    try {
      await fn();
    } catch (e) {
      if (e instanceof ApiError && e.report) setLockReport(e.report);
      else setProblem((e as Error).message);
    } finally {
      setBusy(false);
      onChanged();
    }
  }

  const latest = versions.length ? versions[versions.length - 1].version : 0;

  return (
    <Card title={`Versions of ${dealId}`} actions={busy ? <Spinner /> : undefined}>
      <div className="stack">
        {problem && <Notice kind="error">{problem}</Notice>}
        {lockReport && (
          <div className="stack">
            <Notice kind="error">The agent refused to lock this version:</Notice>
            <Findings report={lockReport} />
          </div>
        )}
        <div className="versions">
          {[...versions].reverse().map((v) => {
            const open = v.version === latest && v.status === "draft";
            return (
              <div key={v.version} className={`version ${v.status === "active" ? "active" : ""}`}>
                <div className="row spread">
                  <strong>Version {v.version}</strong>
                  <span className={`status ${v.status === "active" ? "ok" : v.status === "draft" ? "info" : "neutral"}`}>{v.status}</span>
                </div>
                <p className="muted small">
                  {v.display.price} · royalty {v.display.royalty} · created {when(v.created_at)}
                  {v.locked_at && <> · locked {when(v.locked_at)}</>}
                  {" · "}terms <span className="mono" title={v.terms_hash}>{short(v.terms_hash, 12)}</span>
                </p>
                <ul className="approvals">
                  {v.draft.parties.map((p) => {
                    const a = v.approvals.find((x) => x.party_id === p.id);
                    return (
                      <li key={p.id}>
                        <span>{p.name} <span className="muted small">· {v.display.shares[p.id]}</span></span>
                        {a ? <span className="status ok">✓ approved {when(a.approved_at)}</span>
                          : open ? <button className="small" disabled={busy} onClick={() => act(() => api.approve(dealId, v.version, p.id))}>Approve as {p.name}</button>
                          : <span className="muted small">not approved</span>}
                      </li>
                    );
                  })}
                </ul>
                <div className="row" style={{ marginTop: 10 }}>
                  {open && (
                    <button className="primary small" disabled={busy} onClick={() => act(() => api.lock(dealId, v.version))}>
                      Lock version {v.version}
                    </button>
                  )}
                  {v.version === latest && <button className="small" onClick={() => onEdit(v)}>Change terms (new version)</button>}
                  {open && v.pending_approvals.length > 0 && (
                    <span className="muted small">{v.pending_approvals.length} approval{v.pending_approvals.length > 1 ? "s" : ""} missing; <RuleTag rule="approval-missing" /> will refuse the lock.</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </Card>
  );
}

function AddArtwork({ registry, onAdded, onCancel }: {
  registry: Registry; onAdded: (artwork: RegistryArtwork) => void; onCancel: () => void;
}) {
  const NEW = "__new__";
  const [title, setTitle] = useState("");
  const [consent, setConsent] = useState("10");
  const [holder, setHolder] = useState(NEW);
  const [artistName, setArtistName] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const coOwners = registry.parties.filter((p) => p.kind === "co-owner");
  const shownTitle = title.trim().replace(/^\[placeholder\]\s*/i, "");

  async function submit() {
    setBusy(true); setProblem(null);
    try {
      const out = await api.addArtwork({
        title, consented_editions: consent,
        ...(holder === NEW ? { new_artist_name: artistName } : { rights_holder: holder }),
      });
      onAdded(out.artwork);
    } catch (e) {
      setProblem((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="add-artwork">
      <div className="row spread">
        <h3>Add a synthetic artwork</h3>
        <span className="tag-placeholder">[PLACEHOLDER]</span>
      </div>
      <p className="muted small">
        It's saved with a [PLACEHOLDER] tag and a placeholder consent record, so the demo can be run again
        on a fresh artwork without resetting. Reset everything removes it.
      </p>
      <div className="fields">
        <label className="field"><span>Title</span>
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Blue Hour" />
        </label>
        <label className="field"><span>Editions consented to</span>
          <input inputMode="numeric" value={consent} onChange={(e) => setConsent(e.target.value)} />
        </label>
        <label className="field"><span>Rights holder (the artist)</span>
          <select value={holder} onChange={(e) => setHolder(e.target.value)}>
            <option value={NEW}>New placeholder artist…</option>
            {coOwners.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
        {holder === NEW && (
          <label className="field"><span>Artist's name</span>
            <input value={artistName} onChange={(e) => setArtistName(e.target.value)} placeholder="Amina" />
          </label>
        )}
      </div>
      {shownTitle && <p className="muted small">It will be listed as <strong>[PLACEHOLDER] {shownTitle}</strong>.</p>}
      <div className="row">
        <button className="primary small" disabled={busy || !title.trim()} onClick={submit}>Add artwork</button>
        <button className="small" onClick={onCancel}>Cancel</button>
      </div>
      {problem && <Notice kind="error">{problem}</Notice>}
    </div>
  );
}
