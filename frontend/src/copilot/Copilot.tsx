import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, ReactNode, useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { api } from "../api";
import { cx } from "../ui";

export interface CopilotAction { id: string; kind: string; label: string; summary: string; method: string; path: string; body: Record<string, unknown> }
interface Msg { role: "user" | "assistant"; content: string; actions: CopilotAction[]; tools?: string[]; error?: string }
interface Status { configured: boolean; budget: number; spent: number }

const SUGGESTIONS = [
  "Que dois-je faire en priorité aujourd'hui ?",
  "Quels clients faut-il relancer ?",
  "Résume ma trésorerie et les factures en retard",
  "Résume ce que je vois sur cette page",
];

/** Mise en forme légère (gras, listes, titres, liens) sans HTML brut : rien n'est injecté tel quel. */
function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /\[([^\]]+)\]\(([^)\s]+)\)|\*\*([^*]+)\*\*|`([^`]+)`/g;
  let last = 0, m: RegExpExecArray | null, k = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    if (m[1]) {
      const href = m[2];
      out.push(href.startsWith("/") && !href.startsWith("//")
        ? <Link key={k++} to={href} className="font-medium text-brand-600 underline decoration-brand-600/30 hover:decoration-brand-600">{m[1]}</Link>
        : /^https?:\/\//.test(href) ? <a key={k++} href={href} target="_blank" rel="noreferrer noopener" className="text-brand-600 underline">{m[1]}</a> : m[1]);
    } else if (m[3]) out.push(<b key={k++}>{m[3]}</b>);
    else if (m[4]) out.push(<code key={k++} className="rounded bg-slate-100 px-1 text-[0.9em]">{m[4]}</code>);
    last = re.lastIndex;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Markdown({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let list: ReactNode[] = [];
  const flush = () => { if (list.length) { blocks.push(<ul key={blocks.length} className="my-1 list-disc space-y-0.5 pl-5">{list}</ul>); list = []; } };
  text.split("\n").forEach((line, i) => {
    const li = /^\s*(?:[-*•]|\d+\.)\s+(.*)$/.exec(line);
    if (li) { list.push(<li key={i}>{inline(li[1])}</li>); return; }
    flush();
    const h = /^#{1,4}\s+(.*)$/.exec(line);
    if (h) blocks.push(<p key={i} className="mt-2 font-semibold text-slate-900">{inline(h[1])}</p>);
    else if (line.trim()) blocks.push(<p key={i} className="my-1">{inline(line)}</p>);
  });
  flush();
  return <>{blocks}</>;
}

/** Carte d'une action proposée par l'IA : rien n'est fait sans « Valider ». */
function ActionCard({ action }: { action: CopilotAction }) {
  const qc = useQueryClient();
  const [state, setState] = useState<"idle" | "busy" | "done" | "dismissed">("idle");
  const [error, setError] = useState("");
  const [link, setLink] = useState<string | null>(null);
  const log = (applied: boolean) => api("/copilot/actions/log", "POST", { kind: action.kind, summary: action.summary, applied }).catch(() => undefined);
  const apply = async () => {
    setState("busy"); setError("");
    try {
      const res = await api<{ id?: number }>(action.path.replace(/^\/api/, ""), action.method, action.body);
      if (action.kind === "create_quote" && res?.id) setLink(`/facturation/${res.id}`);
      if (action.kind === "create_company" && res?.id) setLink(`/crm/societes/${res.id}`);
      setState("done"); log(true); qc.invalidateQueries();
    } catch (e) { setState("idle"); setError(e instanceof Error ? e.message : String(e)); }
  };
  return (
    <div className={cx("mt-2 rounded-md border p-3 text-sm transition", state === "done" ? "border-emerald-600/30 bg-emerald-50/60" : state === "dismissed" ? "border-slate-200 opacity-50" : "border-brand-600/30 bg-brand-50/40")}>
      <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-brand-600">Proposé par l'IA</p>
      <p className="mt-0.5 text-slate-800">{action.summary}</p>
      {error && <p className="mt-1 text-xs text-red-700">{error}</p>}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {state === "done" ? <span className="text-xs font-medium text-emerald-800">✓ Fait{link && <> · <Link className="underline" to={link}>Ouvrir</Link></>}</span>
          : state === "dismissed" ? <span className="text-xs text-slate-500">Ignoré</span>
          : <>
            <button disabled={state === "busy"} onClick={apply} className="rounded bg-brand-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-brand-700 disabled:opacity-50">{state === "busy" ? "…" : `✓ ${action.label}`}</button>
            <button onClick={() => { setState("dismissed"); log(false); }} className="rounded px-2.5 py-1 text-xs text-slate-600 ring-1 ring-slate-300 hover:bg-white">Ignorer</button>
          </>}
      </div>
    </div>
  );
}

/** Panneau du copilote : discussion avec l'IA qui lit tout le Hub. */
export default function Copilot({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { pathname } = useLocation();
  const qc = useQueryClient();
  const [convId, setConvId] = useState<number | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState(false);
  const status = useQuery({ queryKey: ["copilot-status"], queryFn: () => api<Status>("/copilot/status"), enabled: open });
  const convs = useQuery({ queryKey: ["copilot-convs"], queryFn: () => api<{ id: number; title: string; updated_at: string }[]>("/copilot/conversations"), enabled: open && history });
  const end = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [msgs]);
  useEffect(() => { if (open) setTimeout(() => box.current?.focus(), 50); }, [open]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !busy && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, busy, onClose]);

  const patchLast = (f: (m: Msg) => Msg) => setMsgs((ms) => ms.map((m, i) => (i === ms.length - 1 ? f(m) : m)));

  const send = async (text: string) => {
    const q = text.trim();
    if (!q || busy) return;
    setInput(""); setBusy(true); setHistory(false);
    setMsgs((ms) => [...ms, { role: "user", content: q, actions: [] }, { role: "assistant", content: "", actions: [], tools: [] }]);
    try {
      const res = await fetch("/api/copilot/chat", {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-Requested-With": "deva2" },
        body: JSON.stringify({ message: q, conversation_id: convId, page: pathname }),
      });
      if (!res.ok || !res.body) throw new Error(res.status === 401 ? "Session expirée : reconnectez-vous." : `Erreur ${res.status}`);
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let cut;
        while ((cut = buf.indexOf("\n\n")) >= 0) {
          const line = buf.slice(0, cut).trim();
          buf = buf.slice(cut + 2);
          if (!line.startsWith("data: ")) continue;
          const ev = JSON.parse(line.slice(6));
          if (ev.type === "conversation") setConvId(ev.id);
          else if (ev.type === "text") patchLast((m) => ({ ...m, content: m.content + ev.text }));
          else if (ev.type === "tool") patchLast((m) => ({ ...m, tools: [...(m.tools ?? []), `${ev.label}${ev.detail ? ` · ${ev.detail}` : ""}`] }));
          else if (ev.type === "action") patchLast((m) => ({ ...m, actions: [...m.actions, ev.action] }));
          else if (ev.type === "error") patchLast((m) => ({ ...m, error: ev.message }));
        }
      }
    } catch (e) {
      patchLast((m) => ({ ...m, error: e instanceof Error ? e.message : String(e) }));
    } finally {
      setBusy(false);
      qc.invalidateQueries({ queryKey: ["copilot-status"] });
      qc.invalidateQueries({ queryKey: ["copilot-convs"] });
    }
  };

  const load = async (id: number) => {
    const c = await api<{ id: number; messages: Msg[] }>(`/copilot/conversations/${id}`);
    setConvId(c.id); setMsgs(c.messages); setHistory(false);
  };
  const reset = () => { if (!busy) { setConvId(null); setMsgs([]); setHistory(false); } };

  if (!open) return null;
  const st = status.data;
  return (
    <div className="fixed inset-0 z-[90] flex justify-end" role="dialog" aria-label="Copilote">
      <div className="tour-fade absolute inset-0 bg-slate-900/30" onClick={() => !busy && onClose()} />
      <section className="copilot-in relative flex h-full w-full flex-col bg-white shadow-2xl sm:max-w-[460px]">
        <header className="flex items-center gap-2 border-b border-slate-200 px-4 py-3">
          <span className="flex h-7 w-7 items-center justify-center rounded-full bg-brand-600 text-sm text-white">✨</span>
          <div className="min-w-0 flex-1">
            <p className="font-serif text-lg font-semibold leading-tight text-slate-900">Copilote</p>
            <p className="truncate text-[11px] text-slate-400">Lit tout le Hub · propose, vous validez</p>
          </div>
          <button onClick={() => setHistory((h) => !h)} className={cx("rounded px-2 py-1 text-xs ring-1", history ? "bg-slate-900 text-white ring-slate-900" : "text-slate-600 ring-slate-200 hover:bg-slate-50")}>Historique</button>
          <button onClick={reset} className="rounded px-2 py-1 text-xs text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50" title="Nouvelle conversation">+ Nouvelle</button>
          <button onClick={onClose} className="px-1 text-slate-400 hover:text-slate-700" aria-label="Fermer">✕</button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 text-sm leading-relaxed text-slate-700">
          {history ? (
            <div>
              <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.1em] text-slate-400">Conversations récentes</p>
              {!convs.data?.length ? <p className="text-slate-400">Aucune conversation.</p> : (
                <ul className="divide-y divide-slate-100">
                  {convs.data.map((c) => (
                    <li key={c.id} className="flex items-center justify-between gap-2 py-2">
                      <button className="min-w-0 flex-1 truncate text-left hover:text-brand-600" onClick={() => load(c.id)}>{c.title}</button>
                      <button className="text-xs text-red-500" onClick={async () => { await api(`/copilot/conversations/${c.id}`, "DELETE"); if (c.id === convId) reset(); convs.refetch(); }}>Supprimer</button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : !msgs.length ? (
            <div className="space-y-4">
              <p className="text-slate-600">Posez une question sur vos clients, vos mails, vos devis, votre trésorerie, vos projets… Le copilote consulte le Hub, fait les liens et vous propose des actions.</p>
              {st && !st.configured && <p className="rounded bg-amber-50 px-3 py-2 text-xs text-amber-800">Renseignez d'abord la clé API Anthropic : Paramètres → Intégrations → Assistant IA.</p>}
              <div className="flex flex-col gap-2">
                {SUGGESTIONS.map((s) => <button key={s} onClick={() => send(s)} className="rounded-md border border-slate-200 px-3 py-2 text-left text-slate-700 transition hover:border-brand-500 hover:bg-brand-50/40">{s}</button>)}
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              {msgs.map((m, i) => m.role === "user" ? (
                <div key={i} className="ml-8 rounded-lg bg-slate-900 px-3 py-2 text-white"><p className="whitespace-pre-wrap">{m.content}</p></div>
              ) : (
                <div key={i}>
                  {(m.tools ?? []).length > 0 && (
                    <div className="mb-1 flex flex-wrap gap-1">
                      {m.tools!.map((t, k) => <span key={k} className="rounded-full bg-stone-100 px-2 py-0.5 text-[11px] text-slate-500">🔎 {t}</span>)}
                    </div>
                  )}
                  {m.content ? <Markdown text={m.content} /> : busy && i === msgs.length - 1 && !m.error && <p className="flex items-center gap-2 text-slate-400"><span className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />Réflexion…</p>}
                  {m.actions.map((a) => <Fragment key={a.id}><ActionCard action={a} /></Fragment>)}
                  {m.error && <p className="mt-1 rounded bg-red-50 px-3 py-2 text-xs text-red-700">{m.error}</p>}
                </div>
              ))}
              <div ref={end} />
            </div>
          )}
        </div>

        <form className="border-t border-slate-200 p-3" onSubmit={(e) => { e.preventDefault(); send(input); }}>
          <div className="flex items-end gap-2">
            <textarea ref={box} rows={2} value={input} disabled={busy} placeholder="Demandez au copilote…  (Entrée pour envoyer)"
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }}
              className="min-h-[44px] resize-none" />
            <button type="submit" disabled={busy || !input.trim()} className="h-10 shrink-0 rounded bg-brand-600 px-3 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-40">Envoyer</button>
          </div>
          {st && <p className="mt-1.5 text-[10px] text-slate-400">Ce mois-ci : {st.spent.toFixed(2)} € / {st.budget.toFixed(0)} € (estimation) · ⌘J pour ouvrir</p>}
        </form>
      </section>
    </div>
  );
}
