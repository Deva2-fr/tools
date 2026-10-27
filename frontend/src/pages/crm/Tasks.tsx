import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Row, User, api } from "../../api";
import { Badge, Button, Card, Empty, ErrorMsg, Loading, PageHeader, cx, fmtDate } from "../../ui";

export default function Tasks({ user }: { user: User }) {
  const qc = useQueryClient();
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const [filter, setFilter] = useState<"todo" | "mine" | "done">("todo");
  const list = useQuery({ queryKey: ["tasks-all"], queryFn: () => api<Row[]>("/crm/tasks") });
  const inval = () => qc.invalidateQueries();
  const add = useMutation({
    mutationFn: () => api("/crm/tasks", "POST", { title, due_date: due || null, assignee_email: user.email }),
    onSuccess: () => { setTitle(""); setDue(""); inval(); },
  });
  const toggle = useMutation({ mutationFn: (id: number) => api(`/crm/tasks/${id}/toggle`, "POST"), onSuccess: inval });
  const del = useMutation({ mutationFn: (id: number) => api(`/crm/tasks/${id}`, "DELETE"), onSuccess: inval });
  const today = new Date().toISOString().slice(0, 10);
  const rows = (list.data ?? []).filter((t) => (filter === "done" ? t.done : !t.done && (filter === "todo" || t.assignee_email === user.email)));
  return (
    <>
      <PageHeader title="Tâches" subtitle="Votre to-do partagée : rappels de relance, rendez-vous à préparer, choses à ne pas oublier." />
      <Card className="mb-6">
        <form className="flex flex-wrap gap-3" onSubmit={(e) => { e.preventDefault(); if (title.trim()) add.mutate(); }}>
          <div className="min-w-[240px] flex-1"><input placeholder="Nouvelle tâche (ex : Relancer Acme pour le devis)" value={title} onChange={(e) => setTitle(e.target.value)} /></div>
          <div className="w-44"><input type="date" value={due} onChange={(e) => setDue(e.target.value)} /></div>
          <Button type="submit" busy={add.isPending}>Ajouter</Button>
        </form>
        <ErrorMsg error={add.error} />
      </Card>
      <div className="mb-4 flex gap-2">
        {([["todo", "À faire"], ["mine", "Mes tâches"], ["done", "Terminées"]] as const).map(([k, l]) => (
          <button key={k} onClick={() => setFilter(k)} className={cx("rounded-full px-4 py-1.5 text-sm font-medium", filter === k ? "bg-brand-600 text-white" : "bg-white text-slate-600 ring-1 ring-slate-200")}>{l}</button>
        ))}
      </div>
      <Card>
        {list.isLoading ? <Loading /> : !rows.length ? <Empty>Rien à faire ici 🎉</Empty> : (
          <ul className="divide-y divide-slate-100">
            {rows.map((t) => (
              <li key={t.id} className="flex items-center gap-3 py-3 text-sm">
                <input type="checkbox" checked={t.done} onChange={() => toggle.mutate(t.id)} />
                <span className={cx("flex-1", t.done && "text-slate-400 line-through")}>{t.title}</span>
                {t.due_date && <Badge tone={t.done ? "slate" : t.due_date < today ? "red" : t.due_date === today ? "amber" : "slate"}>{fmtDate(t.due_date)}</Badge>}
                {t.assignee_email && <span className="hidden text-xs text-slate-400 sm:inline">{t.assignee_email}</span>}
                <button className="text-xs text-red-600" onClick={() => del.mutate(t.id)}>✕</button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}
