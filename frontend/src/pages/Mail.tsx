import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Mail, User, api } from "../api";
import { Badge, Button, Card, Empty, ErrorMsg, Loading, PageHeader, cx, fmtDateTime } from "../ui";

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
const FILTERS = [["todo", "À traiter"], ["all", "Tous"], ["repondu", "Répondus"], ["info", "Informations"]] as const;

export default function MailPage({ user }: { user: User }) {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [filter, setFilter] = useState<string>("todo");
  const box = params.get("boite") ?? ""; // "" = toutes, id d'une boîte, ou "microsoft"
  const status = useQuery({ queryKey: ["mail-status"], queryFn: () => api<Status>("/mail/status"), refetchInterval: 120_000 });
  const mails = useQuery({ queryKey: ["mails", box], queryFn: () => api<Mail[]>(`/mail/messages?mailbox=${encodeURIComponent(box)}`), enabled: !!status.data?.connected, refetchInterval: 120_000 });
  const inval = () => qc.invalidateQueries();
  const sync = useMutation({ mutationFn: () => api<{ new: number; errors: string[] }>(`/mail/sync${/^\d+$/.test(box) ? `?mailbox_id=${box}` : ""}`, "POST"), onSuccess: inval });
  const setTag = useMutation({ mutationFn: ({ id, tag }: { id: number; tag: string }) => api(`/mail/messages/${id}/tag`, "PUT", { tag }), onSuccess: inval });
  const connect = useMutation({ mutationFn: () => api<{ url: string }>("/mail/connect"), onSuccess: (r) => { window.location.href = r.url; } });
  const disconnect = useMutation({ mutationFn: () => api("/mail/disconnect", "POST"), onSuccess: inval });

  useEffect(() => { if (params.get("connected")) { inval(); } }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const st = status.data;
  const boxes = st?.mailboxes ?? [];
  const current = boxes.find((b) => String(b.id) === box);
  const names = Object.fromEntries(boxes.map((b) => [b.id, b.name]));
  const pick = (v: string) => setParams(v ? { boite: v } : {});
  const list = (mails.data ?? []).filter((m) =>
    filter === "all" ? true : filter === "todo" ? ["a_repondre", "urgent"].includes(m.tag) : filter === "repondu" ? ["repondu", "fait"].includes(m.tag) : ["info", "ignore"].includes(m.tag),
  );
  const todo = (mails.data ?? []).filter((m) => ["a_repondre", "urgent"].includes(m.tag)).length;
  const totalTodo = boxes.reduce((a, b) => a + b.todo, 0) + (st?.microsoft.todo ?? 0);
  const webmail = current?.webmail_url || (boxes.length === 1 ? boxes[0].webmail_url : "");
  const sources = boxes.length + (st?.microsoft.connected ? 1 : 0);

  if (status.isLoading) return <Loading />;
  return (
    <>
      <PageHeader title="Mails" subtitle={st?.connected ? (current ? `${current.name} · ${current.username} · lecture seule, actualisée toutes les 5 minutes` : box === "microsoft" ? `Microsoft 365 · ${st.microsoft.mailbox}` : `${sources} boîte(s) · lecture seule, actualisées toutes les 5 minutes`) : "Connectez vos boîtes pour voir quels mails attendent une réponse."}
        action={st?.connected && <div className="flex gap-2">
          {webmail && <a className="inline-flex items-center rounded px-3 py-2 text-sm font-medium text-brand-600 ring-1 ring-slate-200 hover:bg-slate-50" href={webmail} target="_blank" rel="noreferrer noopener">Ouvrir le webmail ↗</a>}
          <Button variant="soft" busy={sync.isPending} onClick={() => sync.mutate()}>Actualiser</Button>
          {user.role === "admin" && box === "microsoft" && <Button variant="ghost" onClick={() => confirm("Déconnecter la boîte Microsoft 365 ?") && disconnect.mutate()}>Déconnecter</Button>}</div>} />
      {st?.connected && sources > 1 && (
        <div className="mb-5 flex flex-wrap gap-2 border-b border-slate-200 pb-4">
          {([["", "Toutes les boîtes", totalTodo, ""], ...boxes.map((b) => [String(b.id), b.name, b.todo, b.last_error] as const), ...(st.microsoft.connected ? [["microsoft", "Microsoft 365", st.microsoft.todo, ""] as const] : [])] as const).map(([k, label, n, err]) => (
            <button key={k} onClick={() => pick(k)} title={err ? `Dernière synchronisation en échec : ${err}` : undefined}
              className={cx("flex items-center gap-2 rounded-md px-3.5 py-2 text-sm font-medium transition", box === k ? "bg-stone-900 text-white" : "bg-white text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50")}>
              {err && <span className="h-2 w-2 rounded-full bg-red-500" />}{label}
              {n > 0 && <span className={cx("rounded-full px-2 text-xs", box === k ? "bg-white/20" : "bg-amber-100 text-amber-800")}>{n}</span>}
            </button>
          ))}
        </div>
      )}
      {current?.last_error && <p className="mb-4 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">Dernière synchronisation de « {current.name} » en échec : {current.last_error}</p>}
      {sync.data?.errors?.length ? <p className="mb-4 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">{sync.data.errors.join(" · ")}</p> : null}
      {params.get("error") && <div className="mb-4"><ErrorMsg error={params.get("error")} /></div>}
      <ErrorMsg error={sync.error} />
      {!st?.connected ? (
        <Card>
          <div className="space-y-2 text-sm text-slate-600">
            <p className="font-medium text-slate-900">Aucune boîte mail connectée</p>
            <p>Ajoutez vos boîtes dans <b>Paramètres → Intégrations → Boîtes mail (IMAP) → + Boîte mail</b> : serveur, port, identifiant et mot de passe, les mêmes que dans Outlook (<i>Fichier → Paramètres du compte</i>). Une boîte par adresse (contact@, compta@…) : chacune aura son bouton ici.</p>
            <p className="text-xs text-slate-400">Le Hub ne fait que lire : il ne marque rien comme lu, n'envoie, ne déplace ni ne supprime aucun mail. Guide : docs/CONFIGURATION.md, section 3.</p>
          </div>
          {st?.microsoft.configured && (
            <div className="mt-4 space-y-2 border-t border-slate-100 pt-4 text-sm text-slate-600">
              <p>Boîte hébergée chez Microsoft 365 ? L'application Microsoft est configurée, il reste à autoriser l'accès.</p>
              {user.role === "admin" ? <Button variant="soft" busy={connect.isPending} onClick={() => connect.mutate()}>Se connecter avec Microsoft</Button> : <p>Demandez à un administrateur de connecter la boîte.</p>}
              <ErrorMsg error={connect.error} />
            </div>
          )}
        </Card>
      ) : (
        <>
          <div className="mb-4 flex flex-wrap gap-2">
            {FILTERS.map(([k, label]) => (
              <button key={k} onClick={() => setFilter(k)} className={cx("rounded px-3 py-1.5 text-sm font-medium transition", filter === k ? "bg-brand-600 text-white" : "bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50")}>
                {label}{k === "todo" && todo > 0 && <span className="ml-2 rounded-full bg-white/25 px-2 text-xs">{todo}</span>}
              </button>
            ))}
          </div>
          {mails.isLoading ? <Loading /> : list.length === 0 ? <Empty>{filter === "todo" ? "Rien à répondre pour l'instant " : "Aucun mail."}</Empty> : (
            <div className="space-y-3">
              {list.map((m) => (
                <Card key={m.id} className={m.is_read ? "" : "border-l-4 border-l-brand-500"}>
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge tone={TAGS[m.tag]?.tone ?? "slate"}>{TAGS[m.tag]?.label ?? m.tag}</Badge>
                        <span className="text-xs text-slate-400">{fmtDateTime(m.received_at)}</span>
                        {!box && sources > 1 && <span className="text-xs font-medium text-slate-500">{m.mailbox_id ? names[m.mailbox_id] : "Microsoft 365"}</span>}
                      </div>
                      <p className="mt-2 truncate font-medium text-slate-900">{m.subject || "(sans objet)"}</p>
                      <p className="text-sm text-slate-500">{m.sender_name} &lt;{m.sender_email}&gt;</p>
                      <p className="mt-1 line-clamp-2 text-sm text-slate-500">{m.preview}</p>
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-1.5 text-xs">
                      {m.web_link && <a className="font-medium text-brand-600" href={m.web_link} target="_blank" rel="noreferrer noopener">{m.mailbox_id ? "Ouvrir le webmail ↗" : "Ouvrir dans Outlook ↗"}</a>}
                      <select className="!w-auto !py-1 text-xs" value="" onChange={(e) => e.target.value && setTag.mutate({ id: m.id, tag: e.target.value })}>
                        <option value="">Changer le tag…</option>
                        <option value="a_repondre">À répondre</option><option value="urgent">Urgent</option>
                        <option value="fait">Traité</option><option value="ignore">Ignorer</option><option value="auto">↺ Tag automatique</option>
                      </select>
                    </div>
                  </div>
                </Card>
              ))}
            </div>
          )}
          <p className="mt-6 text-xs text-slate-400">Le tag « À répondre » est détecté automatiquement (question ou demande, pas de réponse envoyée, expéditeur non automatique). Vous pouvez toujours le corriger à la main.</p>
        </>
      )}
    </>
  );
}
