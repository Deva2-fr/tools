import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Mail, User, api } from "../api";
import { Badge, Button, Card, Empty, ErrorMsg, Loading, Modal, PageHeader, cx, fmtDateTime } from "../ui";

interface Box { id: number; name: string; username: string; webmail_url: string; last_synced_at: string | null; last_error: string; todo: number }
interface Status { mailboxes: Box[]; connected: boolean; microsoft: { connected: boolean; mailbox: string; todo: number; configured: boolean; redirect_uri: string } }

const TAGS: Record<string, { label: string; tone: "red" | "amber" | "green" | "slate" | "blue" }> = {
  urgent: { label: " Urgent – à répondre", tone: "red" },
  a_repondre: { label: "↩ À répondre", tone: "amber" },
  repondu: { label: "✓ Répondu", tone: "green" },
  fait: { label: "✓ Traité", tone: "green" },
  ignore: { label: "Ignoré", tone: "slate" },
  info: { label: "Information", tone: "slate" },
};
const FILTERS = [["todo", "À traiter"], ["all", "Tous les mails"], ["repondu", "Répondus"], ["info", "Informations"]] as const;
const TAG_ACTIONS = [["a_repondre", "À répondre"], ["urgent", "Urgent"], ["fait", "Traité"], ["ignore", "Ignorer"], ["auto", "↺ Automatique"]] as const;

interface Content { id: number; subject: string; from: string[]; to: string[]; cc: string[]; date: string; text: string; html: string; attachments: { index: number; name: string; size: number; type: string }[]; tag: string; web_link: string }

const shortDate = (iso: string) => {
  const d = new Date(iso);
  const today = new Date();
  return d.toDateString() === today.toDateString()
    ? d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString("fr-FR", { day: "numeric", month: "short", ...(d.getFullYear() !== today.getFullYear() ? { year: "numeric" } : {}) });
};
const kb = (n: number) => (n > 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} Mo` : `${Math.max(1, Math.round(n / 1024))} Ko`);

/** HTML d'un mail affiché dans un cadre isolé : aucun script, aucun accès au Hub ; images distantes bloquées
 * par défaut (elles servent souvent à pister la lecture). */
function HtmlBody({ html, images }: { html: string; images: boolean }) {
  const csp = `default-src 'none'; style-src 'unsafe-inline'; img-src data: cid:${images ? " https: http:" : ""}; font-src data:`;
  const doc = `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${csp}"><base target="_blank"><style>body{font:14px/1.55 system-ui,sans-serif;color:#1e293b;margin:0;padding:4px;word-wrap:break-word}img{max-width:100%;height:auto}a{color:#1d6b55}</style></head><body>${html}</body></html>`;
  const [h, setH] = useState(400);
  return <iframe title="Contenu du mail" sandbox="allow-popups allow-popups-to-escape-sandbox" srcDoc={doc} className="w-full rounded border-0 bg-white" style={{ height: h }}
    onLoad={(e) => { try { setH(Math.min(4000, (e.currentTarget.contentDocument?.body.scrollHeight ?? 400) + 24)); } catch { setH(800); } }} />;
}

/** Volet de lecture : le mail complet, lu à la demande sur le serveur. */
function Reader({ id, onTag, boxName, onClose }: { id: number; onTag: (tag: string) => void; boxName: string; onClose: () => void }) {
  const [mode, setMode] = useState<"html" | "text">("html");
  const [images, setImages] = useState(false);
  useEffect(() => { setImages(false); }, [id]);
  const q = useQuery({ queryKey: ["mail-content", id], queryFn: () => api<Content>(`/mail/messages/${id}/content`), staleTime: 300_000 });
  const c = q.data;
  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-3 py-2.5 sm:px-5">
        <button className="whitespace-nowrap text-sm text-slate-500 hover:text-slate-800 lg:hidden" onClick={onClose}>← Retour</button>
        <div className="flex flex-wrap items-center gap-1.5">
          {TAG_ACTIONS.map(([k, label]) => (
            <button key={k} onClick={() => onTag(k)} className={cx("rounded px-2.5 py-1 text-xs font-medium ring-1 transition", c?.tag === k ? "bg-stone-900 text-white ring-stone-900" : "text-slate-600 ring-slate-200 hover:bg-slate-50")}>{label}</button>
          ))}
        </div>
        {c?.web_link && <a className="text-xs font-medium text-brand-600" href={c.web_link} target="_blank" rel="noreferrer noopener">Répondre dans le webmail ↗</a>}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
        {q.isLoading ? <Loading /> : q.error ? <ErrorMsg error={q.error} /> : c && (
          <>
            <h2 className="font-serif text-2xl text-slate-900">{c.subject || "(sans objet)"}</h2>
            <div className="mt-3 space-y-0.5 border-b border-slate-100 pb-4 text-sm">
              <p><span className="text-slate-400">De </span><b className="text-slate-800">{c.from.join(", ")}</b></p>
              {c.to.length > 0 && <p className="text-slate-500"><span className="text-slate-400">À </span>{c.to.join(", ")}</p>}
              {c.cc.length > 0 && <p className="text-slate-500"><span className="text-slate-400">Cc </span>{c.cc.join(", ")}</p>}
              <p className="text-xs text-slate-400">{c.date && fmtDateTime(new Date(c.date).toISOString())} · {boxName}</p>
            </div>
            {c.attachments.length > 0 && (
              <div className="mt-4 flex flex-wrap gap-2">
                {c.attachments.map((a) => (
                  <a key={a.index} href={`/api/mail/messages/${c.id}/attachments/${a.index}`} className="rounded border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs hover:bg-white">
                    📎 {a.name} <span className="text-slate-400">· {kb(a.size)}</span>
                  </a>
                ))}
              </div>
            )}
            {c.html && (
              <div className="mt-4 flex gap-3 text-xs">
                <button className={mode === "html" ? "font-semibold text-slate-800" : "text-brand-600"} onClick={() => setMode("html")}>Mise en forme</button>
                <button className={mode === "text" ? "font-semibold text-slate-800" : "text-brand-600"} onClick={() => setMode("text")}>Texte brut</button>
                {mode === "html" && !images && <button className="ml-auto text-brand-600" onClick={() => setImages(true)}>Afficher les images</button>}
              </div>
            )}
            <div className="mt-3">
              {c.html && mode === "html" ? <HtmlBody html={c.html} images={images} /> : <pre className="whitespace-pre-wrap break-words font-sans text-sm leading-relaxed text-slate-800">{c.text || "(mail vide)"}</pre>}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

const PAGE = 100;

async function fetchMails(path: string): Promise<{ items: Mail[]; total: number; counts: Record<string, number> }> {
  const res = await fetch(`/api${path}`, { credentials: "same-origin", headers: { "X-Requested-With": "deva2" } });
  if (!res.ok) throw new Error(`Erreur ${res.status}`);
  const counts = Object.fromEntries((res.headers.get("X-Counts") ?? "").split(",").filter(Boolean).map((x) => { const [k, v] = x.split("="); return [k, Number(v)]; }));
  return { items: await res.json(), total: Number(res.headers.get("X-Total-Count") ?? 0), counts };
}

/** Explication des tags, telle qu'appliquée par le Hub (services/outlook.py : classify). */
function TagHelp({ onClose }: { onClose: () => void }) {
  return (
    <Modal title="Comment les tags sont-ils attribués ?" onClose={onClose} wide>
      <div className="text-sm text-slate-600">
      <ol className=" list-decimal space-y-2 pl-5">
        <li><b>Votre choix d'abord</b> : un tag posé à la main (menu « Changer le tag ») l'emporte toujours. « Tag automatique » rend la main au Hub.</li>
        <li><b>✓ Répondu</b> : le serveur porte le drapeau « répondu » (posé par Outlook, Thunderbird… quand vous répondez), ou un mail de votre dossier <i>Envoyés</i> répond à ce message (en-têtes In-Reply-To / References : couvre aussi les réponses depuis le téléphone). Un mail que vous aviez marqué « À répondre » passe alors tout seul en « Traité ».</li>
        <li><b>Information</b> : le mail vient de vous-même ou d'un expéditeur automatique (adresse contenant noreply, no-reply, newsletter, notification, mailer-daemon, bounce…).</li>
        <li><b>↩ À répondre</b> : le sujet ou le début du texte contient une question ou une demande : « ? », « merci de », « pouvez-vous », « pourriez-vous », « veuillez », « relance », « rappel », « devis », « facture », « disponibilité », « rendez-vous », « dans l'attente », « retour de votre part », « please », « could you », « asap »…</li>
        <li><b>Urgent</b> : un mail « À répondre » qui contient aussi « urgent », « urgence », « asap », « dernier rappel », « mise en demeure » ou « impayé ».</li>
        <li>Sinon : <b>Information</b>.</li>
      </ol>
      <p className="mt-3 text-xs text-slate-400">La détection est volontairement simple et prudente : corrigez à la main les cas particuliers. Les tags sont recalculés à chaque synchronisation (toutes les 5 minutes).</p>
      </div>
    </Modal>
  );
}

export default function MailPage({ user }: { user: User }) {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [filter, setFilter] = useState<string>("todo");
  const [openId, setOpenId] = useState<number | null>(null);
  const [help, setHelp] = useState(false);
  const box = params.get("boite") ?? ""; // "" = toutes, id d'une boîte, ou "microsoft"
  const status = useQuery({ queryKey: ["mail-status"], queryFn: () => api<Status>("/mail/status"), refetchInterval: 120_000 });
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [limit, setLimit] = useState(PAGE);
  useEffect(() => { const t = setTimeout(() => setQ(search.trim()), 300); return () => clearTimeout(t); }, [search]);
  useEffect(() => setLimit(PAGE), [box, filter, q]);
  const mails = useQuery({
    queryKey: ["mails", box, filter, q, limit],
    queryFn: () => fetchMails(`/mail/messages?mailbox=${encodeURIComponent(box)}&filter=${filter}&q=${encodeURIComponent(q)}&limit=${limit}`),
    enabled: !!status.data?.connected, refetchInterval: 120_000, placeholderData: (prev) => prev,
  });
  const inval = () => qc.invalidateQueries({ predicate: (x) => x.queryKey[0] !== "mail-content" });
  const sync = useMutation({ mutationFn: () => api<{ new: number; errors: string[] }>(`/mail/sync${/^\d+$/.test(box) ? `?mailbox_id=${box}` : ""}`, "POST"), onSuccess: inval });
  const setTag = useMutation({
    mutationFn: ({ id, tag }: { id: number; tag: string }) => api(`/mail/messages/${id}/tag`, "PUT", { tag }),
    onSuccess: (_r, v) => { inval(); qc.invalidateQueries({ queryKey: ["mail-content", v.id] }); },
  });
  const connect = useMutation({ mutationFn: () => api<{ url: string }>("/mail/connect"), onSuccess: (r) => { window.location.href = r.url; } });
  const disconnect = useMutation({ mutationFn: () => api("/mail/disconnect", "POST"), onSuccess: inval });

  useEffect(() => { if (params.get("connected")) { inval(); } }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const st = status.data;
  const boxes = st?.mailboxes ?? [];
  const current = boxes.find((b) => String(b.id) === box);
  const names: Record<number, string> = Object.fromEntries(boxes.map((b) => [b.id, b.name]));
  const pick = (v: string) => { setOpenId(null); setParams(v ? { boite: v } : {}); };
  const list = mails.data?.items ?? [];
  const counts = mails.data?.counts ?? {};
  const totalTodo = boxes.reduce((a, b) => a + b.todo, 0) + (st?.microsoft.todo ?? 0);
  const webmail = current?.webmail_url || (boxes.length === 1 ? boxes[0].webmail_url : "");
  const sources: [string, string, number, string][] = [
    ["", "Toutes les boîtes", totalTodo, ""],
    ...boxes.map((b) => [String(b.id), b.name, b.todo, b.last_error] as [string, string, number, string]),
    ...(st?.microsoft.connected ? [["microsoft", "Microsoft 365", st.microsoft.todo, ""] as [string, string, number, string]] : []),
  ];
  const opened = list.find((m) => m.id === openId);

  if (status.isLoading) return <Loading />;
  if (!st?.connected) {
    return (
      <>
        <PageHeader title="Mails" subtitle="Connectez vos boîtes pour lire vos mails et voir lesquels attendent une réponse." />
        <Card>
          <div className="space-y-2 text-sm text-slate-600">
            <p className="font-medium text-slate-900">Aucune boîte mail connectée</p>
            <p>Ajoutez vos boîtes dans <b>Paramètres → Intégrations → Boîtes mail (IMAP) → + Boîte mail</b> : serveur, port, identifiant et mot de passe, les mêmes que dans Outlook (<i>Fichier → Paramètres du compte</i>). Une boîte par adresse (contact@, compta@…).</p>
            <p className="text-xs text-slate-400">Le Hub ne fait que lire : il ne marque rien comme lu, n'envoie, ne déplace ni ne supprime aucun mail.</p>
          </div>
          {st?.microsoft.configured && (
            <div className="mt-4 space-y-2 border-t border-slate-100 pt-4 text-sm text-slate-600">
              <p>Boîte hébergée chez Microsoft 365 ? L'application Microsoft est configurée, il reste à autoriser l'accès.</p>
              {user.role === "admin" ? <Button variant="soft" busy={connect.isPending} onClick={() => connect.mutate()}>Se connecter avec Microsoft</Button> : <p>Demandez à un administrateur de connecter la boîte.</p>}
              <ErrorMsg error={connect.error} />
            </div>
          )}
        </Card>
      </>
    );
  }

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h1 data-tour="page-title" className="font-serif text-3xl text-slate-900">Mails</h1>
        <div className="flex items-center gap-2">
          <span className="hidden text-xs text-slate-400 sm:inline">Lecture seule · actualisé toutes les 5 min</span>
          {webmail && <a className="inline-flex items-center rounded px-3 py-2 text-sm font-medium text-brand-600 ring-1 ring-slate-200 hover:bg-slate-50" href={webmail} target="_blank" rel="noreferrer noopener">Webmail ↗</a>}
          <Button data-tour="mail-refresh" variant="soft" busy={sync.isPending} onClick={() => sync.mutate()}>Actualiser</Button>
          {user.role === "admin" && box === "microsoft" && <Button variant="ghost" onClick={() => confirm("Déconnecter la boîte Microsoft 365 ?") && disconnect.mutate()}>Déconnecter</Button>}
        </div>
      </div>
      {sync.data?.errors?.length ? <p className="mb-3 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">{sync.data.errors.join(" · ")}</p> : null}
      {params.get("error") && <div className="mb-3"><ErrorMsg error={params.get("error")} /></div>}
      <ErrorMsg error={sync.error} />

      <div className="grid grid-cols-1 overflow-hidden rounded-md border border-slate-200 bg-white lg:h-[calc(100vh-9rem)] lg:grid-cols-[200px_minmax(300px,380px)_1fr]">
        {/* Boîtes et filtres */}
        <aside className={cx("min-w-0 border-b border-slate-200 bg-stone-50 p-3 lg:block lg:border-b-0 lg:border-r", openId !== null && "hidden")}>
          <p className="mb-1 px-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">Boîtes</p>
          {/* Sur mobile : puces défilables ; sur ordinateur : liste verticale */}
          <div data-tour="mail-boxes" className="-mx-3 flex gap-1 overflow-x-auto px-3 pb-1 lg:mx-0 lg:block lg:px-0 lg:pb-0">
          {sources.map(([k, label, n, err]) => (
            <button key={k} onClick={() => pick(k)} title={err ? `Dernière synchronisation en échec : ${err}` : undefined}
              className={cx("flex shrink-0 items-center justify-between gap-2 whitespace-nowrap rounded px-2 py-1.5 text-left text-sm lg:w-full", box === k ? "bg-stone-900 text-white" : "text-slate-700 hover:bg-white")}>
              <span className="flex min-w-0 items-center gap-2 truncate">{err && <span className="h-2 w-2 shrink-0 rounded-full bg-red-500" />}{label}</span>
              {n > 0 && <span className={cx("rounded-full px-1.5 text-[11px]", box === k ? "bg-white/20" : "bg-amber-100 text-amber-800")}>{n}</span>}
            </button>
          ))}
          </div>
          <p className="mb-1 mt-3 px-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400 lg:mt-4">Afficher</p>
          <div data-tour="mail-filters" className="-mx-3 flex gap-1 overflow-x-auto px-3 pb-1 lg:mx-0 lg:block lg:px-0 lg:pb-0">
          {FILTERS.map(([k, label]) => (
            <button key={k} onClick={() => { setFilter(k); setOpenId(null); }}
              className={cx("flex shrink-0 items-center justify-between gap-2 whitespace-nowrap rounded px-2 py-1.5 text-left text-sm lg:w-full", filter === k ? "bg-brand-600 text-white" : "text-slate-700 hover:bg-white")}>
              <span>{label}</span>{counts[k] !== undefined && <span className="text-[11px] opacity-70">{counts[k]}</span>}
            </button>
          ))}
          </div>
          <button data-tour="mail-help" className="mt-3 px-2 text-xs lg:mt-4 text-brand-600 hover:underline" onClick={() => setHelp(true)}>Comment sont attribués les tags ?</button>
          {current?.last_error && <p className="mt-3 rounded bg-red-50 px-2 py-1.5 text-xs text-red-800">Synchronisation en échec : {current.last_error}</p>}
        </aside>

        {/* Liste */}
        <section className={cx("flex min-h-0 min-w-0 flex-col border-b border-slate-200 lg:border-b-0 lg:border-r", openId !== null && "hidden lg:flex")}>
          <div data-tour="mail-search" className="border-b border-slate-200 p-2.5"><input type="search" placeholder="Rechercher : objet, expéditeur, texte…" value={search} onChange={(e) => setSearch(e.target.value)} /></div>
          <div data-tour="mail-list" className="min-h-0 flex-1 overflow-y-auto">
            {mails.isLoading ? <Loading /> : list.length === 0 ? <div className="p-4"><Empty>{q ? `Aucun mail ne correspond à « ${q} ».` : filter === "todo" ? "Rien à répondre pour l'instant." : "Aucun mail."}</Empty></div> : (
              <ul className="divide-y divide-slate-100">
                {list.map((m) => (
                  <li key={m.id}>
                    <button onClick={() => setOpenId(m.id)} className={cx("block w-full px-3.5 py-2.5 text-left transition", openId === m.id ? "bg-brand-50" : "hover:bg-stone-50")}>
                      <div className="flex items-baseline justify-between gap-2">
                        <span className={cx("truncate text-sm", m.is_read ? "text-slate-700" : "font-semibold text-slate-900")}>{m.sender_name || m.sender_email}</span>
                        <span className="shrink-0 text-[11px] text-slate-400">{shortDate(m.received_at)}</span>
                      </div>
                      <p className={cx("truncate text-sm", m.is_read ? "text-slate-600" : "font-medium text-slate-800")}>{m.subject || "(sans objet)"}</p>
                      <div className="mt-0.5 flex items-center gap-2">
                        {m.tag !== "info" && <span className="shrink-0 whitespace-nowrap"><Badge tone={TAGS[m.tag]?.tone ?? "slate"}>{TAGS[m.tag]?.label ?? m.tag}</Badge></span>}
                        <span className="truncate text-xs text-slate-400">{!box && boxes.length > 1 && `${m.mailbox_id ? names[m.mailbox_id] : "M365"} · `}{m.preview}</span>
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {list.length > 0 && (
              <div className="flex items-center justify-between px-3.5 py-3 text-xs text-slate-400">
                <span>{list.length} sur {mails.data?.total ?? list.length}</span>
                {(mails.data?.total ?? 0) > list.length && <Button variant="soft" busy={mails.isFetching} onClick={() => setLimit((l) => l + PAGE)}>Charger plus</Button>}
              </div>
            )}
          </div>
        </section>

        {/* Lecture */}
        <section data-tour="mail-reader" className={cx("min-h-[60vh] min-w-0 lg:min-h-0", openId === null && "hidden lg:block")}>
          {openId !== null ? (
            <Reader id={openId!} boxName={opened?.mailbox_id ? names[opened.mailbox_id] ?? "" : "Microsoft 365"} onClose={() => setOpenId(null)}
              onTag={(tag) => setTag.mutate({ id: openId!, tag })} />
          ) : (
            <div className="flex h-full items-center justify-center p-8 text-center text-sm text-slate-400">Cliquez sur un mail pour le lire en entier.</div>
          )}
        </section>
      </div>
      {help && <TagHelp onClose={() => setHelp(false)} />}
    </>
  );
}
