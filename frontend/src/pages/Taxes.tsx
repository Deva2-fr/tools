import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Tax, api } from "../api";
import { Badge, Button, Card, Empty, ErrorMsg, Field, Loading, Modal, PageHeader, fmtDateTime, fmtMoney } from "../ui";

const CATS: Record<string, string> = { tva: "TVA", is: "Impôt sociétés", cfe: "CFE", social: "Social", comptes: "Comptes annuels", autre: "Autre" };
const REC: Record<string, string> = { none: "Une seule fois", monthly: "Chaque mois", quarterly: "Chaque trimestre", yearly: "Chaque année" };
const blank = { title: "", category: "tva", due_date: "", amount: null as number | null, recurrence: "none", reminder_days: "30,7,1", notes: "", status: "todo" };

function TaxModal({ tax, onClose }: { tax?: Tax; onClose: () => void }) {
  const qc = useQueryClient();
  const [f, setF] = useState(tax ? { title: tax.title, category: tax.category, due_date: tax.due_date, amount: tax.amount, recurrence: tax.recurrence, reminder_days: tax.reminder_days, notes: tax.notes, status: tax.status as string } : blank);
  const save = useMutation({
    mutationFn: () => (tax ? api(`/taxes/${tax.id}`, "PUT", f) : api("/taxes", "POST", f)),
    onSuccess: () => { qc.invalidateQueries(); onClose(); },
  });
  return (
    <Modal title={tax ? "Modifier l'échéance" : "Nouvelle échéance"} onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="space-y-4">
        <Field label="Intitulé *"><input required value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} placeholder="TVA – janvier" /></Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Type"><select value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}>{Object.entries(CATS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
          <Field label="Date limite *"><input type="date" required value={f.due_date} onChange={(e) => setF({ ...f, due_date: e.target.value })} /></Field>
          <Field label="Montant estimé (€)"><input type="number" step="0.01" value={f.amount ?? ""} onChange={(e) => setF({ ...f, amount: e.target.value === "" ? null : Number(e.target.value) })} /></Field>
          <Field label="Répétition"><select value={f.recurrence} onChange={(e) => setF({ ...f, recurrence: e.target.value })}>{Object.entries(REC).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
        </div>
        <Field label="Me prévenir (jours avant)" hint="Séparés par des virgules. Ex : 30,7,1"><input value={f.reminder_days} onChange={(e) => setF({ ...f, reminder_days: e.target.value })} /></Field>
        <Field label="Notes"><textarea rows={2} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
        <ErrorMsg error={save.error} />
        <div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={onClose}>Annuler</Button><Button type="submit" busy={save.isPending}>Enregistrer</Button></div>
      </form>
    </Modal>
  );
}

const d = (iso: string) => new Date(`${iso}T12:00:00`);
const longDate = (iso: string) => d(iso).toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
const monthTitle = (iso: string) => d(iso).toLocaleDateString("fr-FR", { month: "long", year: "numeric" });
const urgency = (t: Tax) => (t.status === "paid" ? "paid" : t.days_left < 0 ? "late" : t.days_left <= 7 ? "soon" : t.days_left <= 30 ? "month" : "later");
const TONE: Record<string, string> = {
  late: "border-red-300 bg-red-50 text-red-800",
  soon: "border-amber-300 bg-amber-50 text-amber-800",
  month: "border-brand-200 bg-brand-50 text-brand-800",
  later: "border-slate-200 bg-white text-slate-700",
  paid: "border-slate-200 bg-slate-50 text-slate-400",
};
const countdown = (t: Tax) => (t.days_left < 0 ? `En retard de ${-t.days_left} j` : t.days_left === 0 ? "Aujourd'hui" : t.days_left === 1 ? "Demain" : `Dans ${t.days_left} jours`);

/** Bloc « calendrier » : la date en grand, colorée selon l'urgence. */
function DateBlock({ t }: { t: Tax }) {
  const date = d(t.due_date);
  return (
    <div className={`flex w-16 shrink-0 flex-col items-center rounded-md border py-1.5 leading-none ${TONE[urgency(t)]}`}>
      <span className="text-[10px] font-semibold uppercase tracking-wide">{date.toLocaleDateString("fr-FR", { month: "short" }).replace(".", "")}</span>
      <span className="my-0.5 font-serif text-2xl font-semibold">{date.getDate()}</span>
      <span className="text-[10px] uppercase">{date.toLocaleDateString("fr-FR", { weekday: "short" }).replace(".", "")}</span>
    </div>
  );
}

interface CalStatus { google_configured: boolean; service_account_email: string; calendar_id: string; calendar_name: string; last_synced_at: string | null; last_error: string }

/** Choix de l'agenda Google où apparaissent les échéances. */
function GoogleCalendar() {
  const qc = useQueryClient();
  const st = useQuery({ queryKey: ["gcal"], queryFn: () => api<CalStatus>("/taxes/google-calendar") });
  const cals = useQuery({ queryKey: ["gcal-list"], queryFn: () => api<{ id: string; name: string }[]>("/taxes/google-calendar/calendars"), enabled: !!st.data?.google_configured, retry: false });
  const [newId, setNewId] = useState("");
  const [open, setOpen] = useState(false);
  const inval = () => { qc.invalidateQueries({ queryKey: ["gcal"] }); qc.invalidateQueries({ queryKey: ["gcal-list"] }); };
  const add = useMutation({ mutationFn: () => api<{ id: string }>("/taxes/google-calendar/calendars", "POST", { calendar_id: newId }), onSuccess: (c) => { setNewId(""); inval(); select.mutate(c.id); } });
  const select = useMutation({ mutationFn: (id: string) => api("/taxes/google-calendar/select", "PUT", { calendar_id: id }), onSuccess: inval });
  const sync = useMutation({ mutationFn: () => api("/taxes/google-calendar/sync", "POST"), onSuccess: inval });
  const s = st.data;
  if (!s) return null;
  return (
    <div className="mb-6 rounded-md border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-sm">
          <p className="font-medium text-slate-900">Google Agenda</p>
          <p className="text-slate-500">
            {!s.google_configured ? <>Renseignez d'abord la clé Google dans <b>Paramètres → Intégrations → Google</b>.</>
              : s.calendar_id ? <>Échéances synchronisées dans <b>{s.calendar_name || s.calendar_id}</b>{s.last_synced_at ? ` · dernière synchronisation ${fmtDateTime(s.last_synced_at)}` : ""} · rappels 7 jours et 1 jour avant.</>
              : "Pas encore relié : choisissez l'agenda où afficher les échéances."}
          </p>
        </div>
        {s.google_configured && (
          <div className="flex flex-wrap items-center gap-2">
            <select className="!w-64" value={s.calendar_id} disabled={select.isPending} onChange={(e) => select.mutate(e.target.value)}>
              <option value="">— Aucun agenda —</option>
              {(cals.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            {s.calendar_id && <Button variant="soft" busy={sync.isPending} onClick={() => sync.mutate()}>Synchroniser</Button>}
            <button className="text-xs text-brand-600" onClick={() => setOpen(!open)}>{open ? "Fermer" : "+ Ajouter un agenda"}</button>
          </div>
        )}
      </div>
      {s.last_error && <p className="mt-3 rounded bg-red-50 px-3 py-2 text-xs text-red-800">{s.last_error}</p>}
      {open && s.google_configured && (
        <div className="mt-4 space-y-3 border-t border-slate-100 pt-4 text-sm text-slate-600">
          <ol className="list-decimal space-y-1 pl-5">
            <li>Dans Google Agenda, ouvrez <b>Paramètres de l'agenda</b> voulu (ex. « Deva2 – Échéances »).</li>
            <li><b>Partager avec des personnes</b> → ajoutez <code className="rounded bg-slate-100 px-1">{s.service_account_email}</code> avec le droit <b>« Apporter des modifications aux événements »</b>.</li>
            <li>Copiez l'<b>ID de l'agenda</b> (section « Intégrer l'agenda ») et collez-le ici.</li>
          </ol>
          <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); add.mutate(); }}>
            <input placeholder="ex. c_abc123…@group.calendar.google.com" value={newId} onChange={(e) => setNewId(e.target.value)} />
            <Button type="submit" className="shrink-0 whitespace-nowrap" busy={add.isPending || select.isPending}>Ajouter et choisir</Button>
          </form>
        </div>
      )}
      <ErrorMsg error={add.error || select.error || sync.error} />
    </div>
  );
}

export default function Taxes() {
  const qc = useQueryClient();
  const [edit, setEdit] = useState<Tax | "new" | null>(null);
  const [showPaid, setShowPaid] = useState(false);
  const [msg, setMsg] = useState("");
  const { data, isLoading } = useQuery({ queryKey: ["taxes"], queryFn: () => api<Tax[]>("/taxes") });
  const inval = () => qc.invalidateQueries();
  const paid = useMutation({ mutationFn: (id: number) => api(`/taxes/${id}/paid`, "POST"), onSuccess: inval });
  const del = useMutation({ mutationFn: (id: number) => api(`/taxes/${id}`, "DELETE"), onSuccess: inval });
  const gen = useMutation({
    mutationFn: (year: number) => api<{ created: number }>(`/taxes/generate?year=${year}`, "POST"),
    onSuccess: (r) => { setMsg(`${r.created} échéance(s) ajoutée(s). Vérifiez les dates avec votre comptable.`); inval(); },
  });

  const rows = (data ?? []).filter((t) => showPaid || t.status === "todo").sort((a, b) => a.due_date.localeCompare(b.due_date));
  const next = rows.find((t) => t.status === "todo" && t.days_left >= 0);
  const late = rows.filter((t) => t.status === "todo" && t.days_left < 0);
  const months: [string, Tax[]][] = [];
  for (const t of rows) {
    const key = t.due_date.slice(0, 7);
    const last = months[months.length - 1];
    if (last && last[0] === key) last[1].push(t);
    else months.push([key, [t]]);
  }
  const year = new Date().getFullYear();
  return (
    <>
      <PageHeader title="Impôts, TVA & déclarations" subtitle="Ne ratez plus une échéance : le Hub vous prévient avant chaque date limite."
        action={<div className="flex gap-2">
          <a href="/api/taxes/calendar.ics"><Button variant="ghost" type="button"> Exporter vers mon agenda</Button></a>
          <Button onClick={() => setEdit("new")}>+ Échéance</Button></div>} />
      {msg && <p className="mb-4 rounded bg-brand-50 px-3 py-2 text-sm text-brand-700">{msg}</p>}
      <GoogleCalendar />
      {late.length > 0 && (
        <p className="mb-3 rounded-md border border-red-300 bg-red-50 px-4 py-2.5 text-sm text-red-800">
          <b>{late.length} échéance(s) dépassée(s) non marquée(s) comme payée(s)</b>, la plus ancienne le <span className="first-letter:uppercase">{longDate(late[0].due_date)}</span> : vérifiez-les ci-dessous (« C'est payé » si c'est fait).
        </p>
      )}
      {next && (
        <div className={`mb-6 flex flex-wrap items-center justify-between gap-4 rounded-md border p-5 ${TONE[urgency(next)]}`}>
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.1em] opacity-80">Prochaine échéance</p>
            <p className="mt-1 font-serif text-3xl first-letter:uppercase">{longDate(next.due_date)}</p>
            <p className="mt-1 text-sm">{next.title}{next.amount != null && <> · <b>{fmtMoney(next.amount)}</b></>}</p>
          </div>
          <div className="text-right">
            <p className="font-serif text-4xl">{next.days_left < 0 ? `J+${-next.days_left}` : `J-${next.days_left}`}</p>
            <p className="text-sm">{countdown(next)}</p>
          </div>
        </div>
      )}
      <ErrorMsg error={gen.error} />
      <Card title="Échéances" action={<label className="flex items-center gap-2 text-xs text-slate-500"><input type="checkbox" checked={showPaid} onChange={(e) => setShowPaid(e.target.checked)} /> Afficher les payées</label>}>
        {isLoading ? <Loading /> : rows.length === 0 ? (
          <div className="space-y-3 text-center">
            <Empty>Aucune échéance à venir.</Empty>
            <div className="flex justify-center gap-2">
              <Button variant="soft" busy={gen.isPending} onClick={() => gen.mutate(year)}>Pré-remplir {year} (TVA, déclaration, CFE)</Button>
              <Button variant="soft" busy={gen.isPending} onClick={() => gen.mutate(year + 1)}>Pré-remplir {year + 1}</Button>
            </div>
          </div>
        ) : (
          <div className="space-y-6">
            {months.map(([key, items]) => (
              <section key={key}>
                <h3 className="mb-2 border-b border-slate-200 pb-1 text-xs font-semibold uppercase tracking-[0.1em] text-slate-500">{monthTitle(items[0].due_date)}</h3>
                <ul className="space-y-2">
                  {items.map((t) => (
                    <li key={t.id} className={`flex flex-wrap items-center gap-4 rounded-md py-1.5 ${t.status === "paid" ? "opacity-60" : ""}`}>
                      <DateBlock t={t} />
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-slate-900">{t.title}</p>
                        <p className="text-xs text-slate-500"><span className="inline-block font-medium text-slate-700 first-letter:uppercase">{longDate(t.due_date)}</span> · {CATS[t.category] ?? t.category}{t.recurrence !== "none" && ` · ${REC[t.recurrence]}`}{t.amount != null && ` · ${fmtMoney(t.amount)}`}</p>
                      </div>
                      <div className="flex items-center gap-3">
                        {t.status === "paid" ? <Badge tone="green">Payée</Badge> : <Badge tone={t.days_left < 0 ? "red" : t.days_left <= 7 ? "amber" : "slate"}>{countdown(t)}</Badge>}
                        {t.status === "todo" && <Button variant="soft" onClick={() => paid.mutate(t.id)}>✓ C'est payé</Button>}
                        <button className="text-xs text-brand-600" onClick={() => setEdit(t)}>Modifier</button>
                        <button className="text-xs text-red-600" onClick={() => confirm("Supprimer cette échéance ?") && del.mutate(t.id)}>Supprimer</button>
                      </div>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        )}
      </Card>
      {rows.length > 0 && <p className="mt-4 text-xs text-slate-400">Échéances pré-remplies : TVA trimestrielle, déclaration annuelle de résultats et CFE (société à l'IS, exercice au 31/12, sans acompte d'IS ni URSSAF). La date exacte de la TVA dépend de votre SIE : confirmez-la avec votre comptable puis ajustez-la ici. <button className="text-brand-600 underline" onClick={() => gen.mutate(year + 1)}>Pré-remplir {year + 1}</button></p>}
      {edit && <TaxModal tax={edit === "new" ? undefined : edit} onClose={() => setEdit(null)} />}
    </>
  );
}
