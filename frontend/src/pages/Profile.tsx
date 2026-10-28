import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { SignatureRow, User, api } from "../api";
import { Badge, Card, Empty, ErrorMsg, Loading, PageHeader, fmtDate, fmtMoney } from "../ui";

/** Signatures de l'utilisateur, avec suppression. */
function Signatures({ userId }: { userId: number }) {
  const qc = useQueryClient();
  const sigs = useQuery({ queryKey: ["signatures", userId], queryFn: () => api<SignatureRow[]>(`/expenses/signatures?user_id=${userId}`) });
  const del = useMutation({
    mutationFn: (id: number) => api(`/expenses/signatures/${id}`, "DELETE"),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["signatures"] }); qc.invalidateQueries({ queryKey: ["profile"] }); },
  });
  const rows = (sigs.data ?? []).filter((x) => x.user_id === userId);
  return (
    <Card title={`Signatures (${rows.length})`} className="mt-6">
      {!rows.length ? <Empty>Aucune signature. Créez-en une depuis une note de frais (« + Nouvelle »).</Empty> : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {rows.map((x) => (
            <div key={x.id} className="rounded border border-slate-200 p-2">
              <img alt={x.name} src={`/api/expenses/signatures/${x.id}/image`} className="h-16 w-full bg-white object-contain" />
              <div className="mt-1 flex items-center justify-between text-xs">
                <span className="truncate text-slate-600">{x.name}</span>
                <button className="text-red-600" disabled={del.isPending}
                  onClick={() => confirm(`Supprimer la signature « ${x.name} » ? Elle disparaîtra des notes de frais où elle est utilisée (les PDF déjà générés ne changent pas).`) && del.mutate(x.id)}>Supprimer</button>
              </div>
            </div>
          ))}
        </div>
      )}
      <ErrorMsg error={del.error} />
    </Card>
  );
}

interface Summary {
  user: { id: number; name: string; email: string; role: string; is_active: boolean; totp_enabled: boolean; created_at: string; signer_roles: string[] };
  expenses: { count: number; year_count: number; year_total: number; total: number; without_receipt: number; recent: { id: number; date: string; reason: string; amount: number; receipts: number }[] };
  subscriptions: { count: number; active: number; annual_cost: number; items: { id: number; name: string; vendor: string; annual_cost: number; renewal_date: string | null; active: boolean }[] };
  signatures: number;
  tasks: { open: number; overdue: number };
  opportunities: { open: number; amount: number };
  time: { month_hours: number };
}

const ROLE: Record<string, string> = { admin: "Administrateur", manager: "Manager", member: "Membre" };
const SIGNER: Record<string, string> = { president: "Président", partner: "Associé" };

function Stat({ label, value, sub, to, tone }: { label: string; value: string | number; sub?: string; to?: string; tone?: string }) {
  const body = (
    <>
      <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500">{label}</p>
      <p className={`mt-2 font-serif text-2xl ${tone ?? ""}`}>{value}</p>
      {sub && <p className="mt-1 text-xs text-slate-400">{sub}</p>}
    </>
  );
  return to ? <Link to={to} className="bg-white p-4 transition hover:bg-stone-50">{body}</Link> : <div className="bg-white p-4">{body}</div>;
}

/** Profil d'un utilisateur : tout ce qui lui est rattaché dans le Hub. */
export default function Profile({ me }: { me: User }) {
  const { id } = useParams();
  const uid = id ? Number(id) : me.id;
  const q = useQuery({ queryKey: ["profile", uid], queryFn: () => api<Summary>(`/users/${uid}/summary`) });
  if (q.error) return <ErrorMsg error={q.error} />;
  if (!q.data) return <Loading />;
  const { user: u, expenses: ex, subscriptions: subs } = q.data;
  return (
    <>
      <PageHeader title={u.name} subtitle={`${u.email} · ${ROLE[u.role] ?? u.role}${u.signer_roles.length ? ` · ${u.signer_roles.map((r) => SIGNER[r]).join(", ")} (signataire des notes de frais)` : ""}`}
        action={<div className="flex flex-wrap gap-2">{!u.is_active && <Badge tone="red">Désactivé</Badge>}<Badge tone={u.totp_enabled ? "green" : "amber"}>{u.totp_enabled ? "2FA activée" : "2FA non activée"}</Badge></div>} />
      <div className="mb-6 grid grid-cols-2 gap-px overflow-hidden rounded-md border border-slate-300 bg-slate-300 lg:grid-cols-6">
        <Stat label="Notes de frais" value={ex.count} sub={`${ex.year_count} cette année · ${fmtMoney(ex.year_total)}`} to="/notes-de-frais" />
        <Stat label="Sans justificatif" value={ex.without_receipt} tone={ex.without_receipt ? "text-amber-700" : ""} sub="notes à compléter" />
        <Stat label="Abonnements" value={subs.active} sub={`${fmtMoney(subs.annual_cost)} HT / an${subs.count > subs.active ? ` · ${subs.count - subs.active} inactif(s)` : ""}`} to="/abonnements" />
        <Stat label="Signatures" value={q.data.signatures} sub="enregistrées" />
        <Stat label="Tâches ouvertes" value={q.data.tasks.open} tone={q.data.tasks.overdue ? "text-red-700" : ""} sub={q.data.tasks.overdue ? `${q.data.tasks.overdue} en retard` : "aucune en retard"} to="/crm/taches" />
        <Stat label="Temps ce mois-ci" value={`${q.data.time.month_hours} h`} sub={`${q.data.opportunities.open} opportunité(s) · ${fmtMoney(q.data.opportunities.amount)}`} to="/temps" />
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title={`Dernières notes de frais (${ex.count})`}>
          {!ex.recent.length ? <Empty>Aucune note de frais.</Empty> : (
            <ul className="divide-y divide-slate-100 text-sm">
              {ex.recent.map((e) => (
                <li key={e.id} className="flex items-center justify-between gap-3 py-2">
                  <span className="min-w-0"><span className="text-slate-400">{fmtDate(e.date)}</span> · <span className="truncate">{e.reason}</span></span>
                  <span className="flex shrink-0 items-center gap-2">{!e.receipts && <Badge tone="amber">sans justificatif</Badge>}<b>{fmtMoney(e.amount)}</b></span>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-3 text-xs text-slate-400">Total depuis le début : {fmtMoney(ex.total)}</p>
        </Card>
        <Card title={`Abonnements (${subs.count})`}>
          {!subs.items.length ? <Empty>Aucun abonnement rattaché.</Empty> : (
            <ul className="divide-y divide-slate-100 text-sm">
              {subs.items.map((x) => (
                <li key={x.id} className={`flex items-center justify-between gap-3 py-2 ${x.active ? "" : "opacity-50"}`}>
                  <span><b>{x.name}</b>{x.vendor && <span className="text-slate-400"> · {x.vendor}</span>}</span>
                  <span className="text-right text-xs text-slate-500">{fmtMoney(x.annual_cost)} / an<br />{x.renewal_date ? `renouvellement ${fmtDate(x.renewal_date)}` : "—"}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
      <Signatures userId={u.id} />
      <p className="mt-6 text-xs text-slate-400">Compte créé le {fmtDate(u.created_at)}.</p>
    </>
  );
}
