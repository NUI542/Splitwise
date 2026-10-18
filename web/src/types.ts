// Shapes returned by the API (api/main.py -> agent/service.py).

export type Severity = "error" | "warning";

export interface Finding {
  rule: string;
  severity: Severity;
  field: string;
  field_label: string;
  statement: string;
  detail: string;
  data: Record<string, unknown>;
}

export interface Report {
  valid: boolean;
  errors: Finding[];
  warnings: Finding[];
  facts?: string[];
}

export interface SummaryLine {
  party: string;
  name: string;
  role: string;
  share_bps: number;
  share_display: string;
  amount_minor: number;
  amount_display: string;
}

export interface CheckReport extends Report {
  version: number;
  terms_hash: string;
  facts: string[];
  summary: { text: string[]; price_minor: number; lines: SummaryLine[] } | null;
}

export interface DraftParty {
  id: string;
  name: string;
  role: string;
  wallet: string | null;
}

export interface DraftShare {
  party_id: string;
  kind: string;
  value: string | number | null;
}

export interface Draft {
  artwork_id: string | null;
  currency: string | null;
  edition_count: string | number | null;
  price: string | number | null;
  price_currency?: string | null;
  royalty_percent: string | number | null;
  parties: DraftParty[];
  shares: DraftShare[];
}

export interface VersionView {
  deal_id: string;
  version: number;
  status: "active" | "superseded" | "draft" | "never locked";
  terms_hash: string;
  created_at: string;
  locked_at: string | null;
  approvals: { party_id: string; party_name: string; approved_at: string }[];
  pending_approvals: string[];
  display: { price: string | null; royalty: string | null; shares: Record<string, string>; artwork_title: string | null };
  draft: Draft;
}

export interface DealListItem {
  deal_id: string;
  latest_version: number;
  active_version: number | null;
  artwork_id: string;
  artwork_title: string | null;
  mint_address: string;
}

export interface Line {
  party: string;
  name: string;
  role: string;
  wallet: string;
  amount_minor: number;
  amount_display: string;
}

export interface Sale {
  sale_id: string;
  deal_id: string;
  deal_version: number;
  type: "primary" | "resale";
  edition: number;
  price_minor: number;
  price_display: string;
  currency: string;
  seller: string;
  seller_name: string;
  buyer: string;
  buyer_name: string;
  sale_at: string;
  tx: string;
  lines: Line[];
  replayed?: boolean;
}

export interface StepRow {
  rule: string;
  statement: string;
  party: string | null;
  inputs: Record<string, string | number>;
  calculation: string;
  result: string;
  values: Record<string, unknown>;
}

export interface Explanation {
  sale_id: string;
  party: string | null;
  deal_id: string;
  deal_version: number;
  lines: Line[];
  trace: { version: number; type: string; steps: StepRow[] };
  explanation: string;
}

export interface Owed {
  party: string;
  name: string;
  wallet: string;
  due_minor: number;
  received_minor: number;
  short_minor: number;
  due_display: string;
  received_display: string;
  amount_display: string;
}

export type Classification = "PRIMARY_SALE" | "SALE_ROYALTY_PAID" | "SALE_ROYALTY_MISSING" | "TRANSFER_UNVERIFIED";
export type FlagStatus = "OPEN" | "RESOLVED" | "DISMISSED";

export interface WatchRow {
  deal_id: string;
  tx: string;
  edition: number;
  classification: Classification;
  rule: string;
  statement: string;
  deal_version: number | null;
  evidence: Record<string, unknown>;
  evidence_display: Record<string, string>;
  owed: Owed[];
  total_owed_minor: number;
  total_owed_display: string | null;
  seq: number;
  at: string;
  flag_id: string | null;
  status: FlagStatus | null;
}

export interface Flag {
  flag_id: string;
  tx: string;
  deal_id: string;
  edition: number;
  classification: Classification;
  rule: string;
  statement: string;
  deal_version: number | null;
  owed: Owed[];
  evidence: Record<string, unknown>;
  evidence_display: Record<string, string>;
  status: FlagStatus;
  created_at: string;
  updated_at: string;
  history: { status: FlagStatus; reason: string; at: string }[];
  explanation: string;
  steps: StepRow[];
  total_owed_minor: number;
  total_owed_display: string;
}

export interface RegistryParty {
  id: string;
  name: string;
  kind: "co-owner" | "collector";
  wallets: string[];
}

export interface RegistryArtwork {
  id: string;
  title: string;
  rights_holder: string;
  consented_editions: number;
  consent_reference: string;
}

export interface Registry {
  _notice: string;
  artworks: RegistryArtwork[];
  parties: RegistryParty[];
}

export interface SimResult {
  scenario: string;
  note: string;
  deal_id?: string;
  sale?: Sale;
  transfer?: { tx: string; edition: number; from: string; to: string; payments: { from: string; to: string; amount_minor: number }[] };
}
