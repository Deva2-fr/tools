import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Row, api } from "../../api";
import { FormModal, defaults } from "../../components";
import { Badge, Button, ErrorMsg, Loading, PageHeader, cx, fmtDate, fmtMoney } from "../../ui";
import { STAGES, oppFields } from "./shared";

interface Summary { stages: Record<string, { count: number; amount: number; weighted: number }>; open_amount: number; forecast: number; won_amount: number }

export default function Pipeline() {
  const qc = useQueryClient();
  const [edit, setEdit] = useState<Row | "new" | null>(null);
  const [drag, setDrag] = useState<number | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const opps = useQuery({ queryKey: ["opps"], queryFn: () => api<Row[]>("/crm/opportunities") });
  const sum = useQuery({ queryKey: ["pipeline-sum"], queryFn: () => api<Summary>("/crm/pipeline/summary") });
  const companies = useQuery({ queryKey: ["ref", "/crm/companies"], queryFn: () => api<Row[]>("/crm/companies?limit=1000") });
  const names = Object.fromEntries((companies.data ?? []).map((c) => [c.id, c.name]));
  const inval = () => qc.invalidateQueries();
  const move = useMutation({ mutationFn: ({ id, stage }: { id: number; stage: string }) => api(`/crm/opportunities/${id}/stage`, "POST", { stage }), onSuccess: inval });
  const save = useMutation({
    mutationFn: (b: Record<string, unknown>) => (edit && edit !== "new" ? api(`/crm/opportunities/${edit.id}`, "PUT", b) : api("/crm/opportunities", "POST", b)),
    onSuccess: () => { inval(); setEdit(null); },
  });
  const del = useMutation({ mutationFn: (id: number) => api(`/crm/opportunities/${id}`, "DELETE"), onSuccess: () => { inval(); setEdit(null); } });

  if (opps.isLoading || !sum.data) return <Loading />;
  const s = sum.data;
  return (
    <>
      <PageHeader title="Pipeline commercial" subtitle="Glissez les cartes d'une colonne à l'autre pour faire avancer vos affaires." action={<Button onClick={() => { save.reset(); setEdit("new"); }}>+ Nouvelle affaire</Button>} />
      <div className="mb-5 grid grid-cols-3 gap-px overflow-hidden rounded-md border border-slate-300 bg-slate-300">
        {[["En cours", fmtMoney(s.open_amount)], ["Prévision pondérée", fmtMoney(s.forecast)], ["Gagné", fmtMoney(s.won_amount)]].map(([l, v]) => (
          <div key={l} className="bg-white p-4"><p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500">{l}</p><p className="mt-1 font-serif text-2xl">{v}</p></div>
        ))}
      </div>
      <ErrorMsg error={move.error} />
      <div className="flex gap-3 overflow-x-auto pb-4">
        {STAGES.map((st) => {
          const items = (opps.data ?? []).filter((o) => o.stage === st.key);
          return (
            <div
              key={st.key}
              onDragOver={(e) => { e.preventDefault(); setOver(st.key); }}
              onDragLeave={() => setOver(null)}
              onDrop={() => { if (drag != null) move.mutate({ id: drag, stage: st.key }); setDrag(null); setOver(null); }}
              className={cx("w-64 shrink-0 rounded-md border-t-4 bg-slate-100/70 p-2 transition", st.tone, over === st.key && "bg-brand-50 ring-2 ring-brand-500")}
            >
              <div className="mb-2 flex items-center justify-between px-1 text-sm font-semibold"><span>{st.label}</span><Badge>{items.length}</Badge></div>
              <p className="mb-2 px-1 text-xs text-slate-400">{fmtMoney(s.stages[st.key]?.amount ?? 0)}</p>
              <div className="min-h-[120px] space-y-2">
                {items.map((o) => (
                  <div key={o.id} draggable onDragStart={() => setDrag(o.id)} onDragEnd={() => setDrag(null)} onClick={() => { save.reset(); setEdit(o); }}
                    className="cursor-grab rounded border border-slate-200 bg-white p-3 text-sm hover:border-brand-500 active:cursor-grabbing">
                    <p className="font-medium text-slate-900">{o.title}</p>
                    <p className="text-xs text-slate-500">{names[o.company_id] ?? "Sans société"}</p>
                    <div className="mt-2 flex items-center justify-between text-xs">
                      <b>{fmtMoney(o.amount)}</b><span className="text-slate-400">{o.probability}%</span>
                    </div>
                    {o.expected_close && <p className="mt-1 text-xs text-slate-400"> {fmtDate(o.expected_close)}</p>}
                    {o.next_action && <p className="mt-1 truncate text-xs text-brand-600">→ {o.next_action}</p>}
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
      {edit && (
        <FormModal title={edit === "new" ? "Nouvelle affaire" : "Modifier l'affaire"} fields={oppFields} initial={edit === "new" ? defaults(oppFields, { amount: 0, probability: 10, stage: "prospect" }) : edit}
          onClose={() => setEdit(null)} onSubmit={(b) => save.mutate(b)} busy={save.isPending} error={save.error} />
      )}
      {edit && edit !== "new" && <div className="fixed bottom-4 right-4 z-50"><Button variant="danger" onClick={() => confirm("Supprimer cette affaire ?") && del.mutate(edit.id)}>Supprimer l'affaire</Button></div>}
    </>
  );
}
