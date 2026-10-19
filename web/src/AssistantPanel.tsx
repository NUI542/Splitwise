import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "./api";
import { when } from "./components";
import type { AssistantStatus, ChatMessage } from "./types";

const STARTERS = [
  "Which edition deals are in force?",
  "Who was paid what in the latest sales?",
  "Were any resales made without paying the royalty?",
  "Explain the open flags.",
];

function merge(current: ChatMessage[], incoming: ChatMessage[]): ChatMessage[] {
  if (!incoming.length) return current;
  const byId = new Map(current.map((m) => [m.id, m]));
  for (const m of incoming) byId.set(m.id, m);
  return [...byId.values()].sort((a, b) => a.id - b.id);
}

/** "Ask the agent": a chat with Omega, which answers using the deal agent's skills. */
export function AssistantPanel() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [status, setStatus] = useState<AssistantStatus | null>(null);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [seenId, setSeenId] = useState(0);
  const lastId = useRef(0);
  const listEnd = useRef<HTMLDivElement>(null);

  lastId.current = messages.length ? messages[messages.length - 1].id : 0;

  // Poll for new messages: often while the panel is open, now and then while it's closed.
  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const r = await api.chat(Math.max(0, lastId.current - 20)); // re-read recent ones to pick up "delivered"
        if (cancelled) return;
        setMessages((m) => merge(m, r.messages));
        setStatus(r.status);
      } catch {
        if (!cancelled) setStatus(null);
      }
    };
    poll();
    const timer = window.setInterval(poll, open ? 1500 : 8000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [open]);

  useEffect(() => {
    if (open) {
      setSeenId(lastId.current);
      listEnd.current?.scrollIntoView({ block: "end" });
    }
  }, [open, messages.length]);

  async function send(question: string) {
    const q = question.trim();
    if (!q || sending) return;
    setSending(true); setProblem(null);
    try {
      const r = await api.ask(q);
      setMessages((m) => merge(m, [r.message]));
      setStatus(r.status);
      setText("");
    } catch (e) {
      setProblem(e instanceof ApiError ? e.message : "Couldn't reach the deal agent.");
    } finally {
      setSending(false);
    }
  }

  const unread = messages.filter((m) => m.role === "agent" && m.id > seenId).length;
  // Omega posts a startup message when it connects; the conversation starts with the first question.
  const asked = messages.some((m) => m.role === "user");
  const last = messages[messages.length - 1];
  const waiting = last?.role === "user";
  const online = !!status?.connected;

  return (
    <>
      <button className="assistant-fab" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className={`dot ${online ? "on" : "off"}`} aria-hidden /> Ask the agent
        {!open && unread > 0 && <span className="unread">{unread}</span>}
      </button>

      {open && (
        <aside className="assistant-drawer" aria-label="Ask the agent">
          <header className="assistant-head">
            <div>
              <h2>Ask the agent</h2>
              <small>Omega, answering with the deal agent's skills</small>
            </div>
            <button className="link" onClick={() => setOpen(false)} aria-label="Close">Close</button>
          </header>
          <div className={`assistant-status ${online ? "on" : "off"}`}>
            <span className={`dot ${online ? "on" : "off"}`} aria-hidden />
            {status ? status.detail : "Can't reach the deal agent's API."}
          </div>

          <div className="assistant-messages">
            {!asked && (
              <div className="assistant-empty">
                <p>Ask about deals, sales, payouts or royalties. Omega reads your question with a language
                  model and answers with the deal agent's own results, so every amount comes from the rules.</p>
              </div>
            )}
            {messages.map((m) => (
              <div key={m.id} className={`bubble ${m.role}`}>
                <div className="bubble-text">{m.text}</div>
                <div className="bubble-meta">
                  {m.role === "agent" ? "Omega" : "You"} · {when(m.at)}
                  {m.role === "user" && m.delivered === false && " · waiting for Omega"}
                </div>
              </div>
            ))}
            {waiting && (
              <div className="assistant-thinking">
                {online ? "Omega is working on it…" : "Your message will reach Omega as soon as it connects."}
              </div>
            )}
            <div ref={listEnd} />
          </div>

          {!asked && (
            <div className="assistant-starters">
              {STARTERS.map((s) => (
                <button key={s} className="chip" disabled={sending} onClick={() => send(s)}>{s}</button>
              ))}
            </div>
          )}
          {problem && <div className="assistant-problem">{problem}</div>}
          <form className="assistant-input" onSubmit={(e) => { e.preventDefault(); send(text); }}>
            <textarea
              rows={2}
              value={text}
              placeholder="Ask about a deal, a sale or a royalty…"
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(text); }
              }}
            />
            <button className="primary" type="submit" disabled={sending || !text.trim()}>Send</button>
          </form>
        </aside>
      )}
    </>
  );
}
