import type {
  CheckReport, DealListItem, Draft, Explanation, Flag, FlagStatus, Registry, Report, Sale, SimResult,
  VersionView, WatchRow,
} from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public report?: Report,
  ) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new ApiError(res.status, data.error ?? "error", data.message ?? res.statusText, data.report);
  }
  return data as T;
}

export const api = {
  registry: () => request<Registry>("GET", "/registry"),
  samples: () => request<{ valid: Draft; invalid: Draft }>("GET", "/samples"),
  deals: () => request<DealListItem[]>("GET", "/deals"),
  check: (draft: Draft, dealId?: string | null) =>
    request<CheckReport>("POST", "/deals/check", { ...draft, deal_id: dealId ?? null }),
  saveVersion: (draft: Draft, dealId?: string | null) =>
    request<{ deal_id: string; version: number; unchanged: boolean }>("POST", "/deals", { ...draft, deal_id: dealId ?? null }),
  versions: (dealId: string) => request<VersionView[]>("GET", `/deals/${dealId}/versions`),
  approve: (dealId: string, version: number, partyId: string) =>
    request<VersionView>("POST", `/deals/${dealId}/approve`, { version, party_id: partyId }),
  lock: (dealId: string, version: number) =>
    request<{ locked_at: string }>("POST", `/deals/${dealId}/lock`, { version }),
  sales: (dealId?: string) => request<Sale[]>("GET", dealId ? `/sales?deal_id=${dealId}` : "/sales"),
  explain: (saleId: string, party?: string | null) =>
    request<Explanation>("GET", `/sales/${encodeURIComponent(saleId)}/explain${party ? `?party=${encodeURIComponent(party)}` : ""}`),
  scan: () => request<WatchRow[]>("POST", "/watch/scan"),
  flags: (status?: FlagStatus) => request<Flag[]>("GET", status ? `/flags?status=${status}` : "/flags"),
  updateFlag: (flagId: string, status: FlagStatus, reason: string) =>
    request<Flag>("PATCH", `/flags/${flagId}`, { status, reason }),
  sim: (scenario: string, params: Record<string, unknown> = {}) =>
    request<SimResult>("POST", `/sim/${scenario}`, params),
  chain: (dealId: string) => request<ChainView>("GET", `/chain/transfers?deal_id=${dealId}`),
};

export interface ChainView {
  transfers: {
    tx: string; edition: number; from_wallet: string; to_wallet: string; ts: number; seq: number;
    paid_minor: number; paid_display: string | null;
  }[];
  payments: { tx: string; from_wallet: string; to_wallet: string; amount_minor: number; currency: string; amount_display: string }[];
}

/** Display name for a party ID or wallet, from the registry (presentation only). */
export function nameOf(registry: Registry, idOrWallet: string): string {
  const byId = registry.parties.find((p) => p.id === idOrWallet);
  if (byId) return byId.name;
  const byWallet = registry.parties.find((p) => p.wallets.includes(idOrWallet));
  if (byWallet) return byWallet.name;
  if (idOrWallet.startsWith("mint:")) return `Mint (${idOrWallet.slice(5)})`;
  return idOrWallet;
}
