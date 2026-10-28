import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ReactNode, useState } from "react";
import { Row, api, downloadFile } from "./api";
import { Button, Card, Empty, ErrorMsg, Field, Loading, Modal, PageHeader, cx } from "./ui";

export type Opt = [string | number, string];
export interface FieldDef {
  name: string;
  label: string;
  type?: "text" | "email" | "number" | "date" | "select" | "checkbox" | "textarea" | "ref";
  options?: Opt[];
  ref?: { endpoint: string; label: (r: Row) => string };
  required?: boolean;
  hint?: string;
  wide?: boolean;
  step?: string;
}
export interface Column {
  label: string;
  render: (r: Row) => ReactNode;
  right?: boolean;
}

/** Options d'un champ « lien » (ex : la liste des sociétés). */
export function useRefOptions(endpoint?: string, label?: (r: Row) => string): Opt[] {
  const q = useQuery({
    queryKey: ["ref", endpoint],
    queryFn: () => api<Row[]>(`${endpoint}?limit=1000`),
    enabled: !!endpoint,
    staleTime: 30_000,
  });
  return (q.data ?? []).map((r) => [r.id, label ? label(r) : String(r.id)] as Opt);
}

function RefSelect({ f, value, onChange }: { f: FieldDef; value: unknown; onChange: (v: number | null) => void }) {
  const opts = useRefOptions(f.ref?.endpoint, f.ref?.label);
  return (
    <select value={value == null ? "" : String(value)} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
      <option value="">— Aucun —</option>
      {opts.map(([v, l]) => (
        <option key={v} value={v}>{l}</option>
      ))}
    </select>
  );
}

export function FieldInput({ f, value, onChange }: { f: FieldDef; value: unknown; onChange: (v: unknown) => void }) {
  const t = f.type ?? "text";
  if (t === "checkbox")
    return (
      <label className="flex items-center gap-2 pt-5 text-sm">
        <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} /> {f.label}
      </label>
    );
  return (
    <Field label={f.label + (f.required ? " *" : "")} hint={f.hint}>
      {t === "textarea" ? (
        <textarea rows={3} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />
      ) : t === "select" ? (
        <select value={String(value ?? "")} onChange={(e) => onChange(typeof f.options![0][0] === "number" ? Number(e.target.value) : e.target.value)}>
          {f.options!.map(([v, l]) => (
            <option key={v} value={v}>{l}</option>
          ))}
        </select>
      ) : t === "ref" ? (
        <RefSelect f={f} value={value} onChange={onChange} />
      ) : t === "number" ? (
        <input
          type="number"
          step={f.step ?? "any"}
          required={f.required}
          value={value == null ? "" : String(value)}
          onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
        />
      ) : (
        <input type={t} required={f.required} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />
      )}
    </Field>
  );
}

/** Convertit l'état du formulaire en corps JSON propre (dates vides → null). */
export function cleanBody(fields: FieldDef[], state: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of fields) {
    const v = state[f.name];
    out[f.name] = f.type === "date" && (v === "" || v === undefined) ? null : v;
  }
  return out;
}

export function FormModal({
  title,
  fields,
  initial,
  onClose,
  onSubmit,
  busy,
  error,
  submitLabel = "Enregistrer",
  top,
}: {
  title: string;
  fields: FieldDef[];
  initial: Record<string, unknown>;
  onClose: () => void;
  onSubmit: (body: Record<string, unknown>) => void;
  busy?: boolean;
  error?: unknown;
  submitLabel?: string;
  /** Contenu affiché au-dessus des champs ; `patch` met à jour plusieurs champs d'un coup. */
  top?: (patch: (values: Record<string, unknown>) => void) => ReactNode;
}) {
  const [state, setState] = useState<Record<string, unknown>>({ ...initial });
  const patch = (values: Record<string, unknown>) => setState((s) => ({ ...s, ...values }));
  return (
    <Modal title={title} onClose={onClose} wide>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          onSubmit(cleanBody(fields, state));
        }}
        className="grid gap-4 sm:grid-cols-2"
      >
        {top && <div className="sm:col-span-2">{top(patch)}</div>}
        {fields.map((f) => (
          <div key={f.name} className={f.wide || f.type === "textarea" ? "sm:col-span-2" : ""}>
            <FieldInput f={f} value={state[f.name]} onChange={(v) => setState((s) => ({ ...s, [f.name]: v }))} />
          </div>
        ))}
        <div className="sm:col-span-2"><ErrorMsg error={error} /></div>
        <div className="flex flex-wrap justify-end gap-2 sm:col-span-2">
          <Button type="button" variant="ghost" onClick={onClose}>Annuler</Button>
          <Button type="submit" busy={busy}>{submitLabel}</Button>
        </div>
      </form>
    </Modal>
  );
}

export function defaults(fields: FieldDef[], extra: Record<string, unknown> = {}): Record<string, unknown> {
  const d: Record<string, unknown> = {};
  for (const f of fields)
    d[f.name] =
      f.type === "checkbox" ? false : f.type === "number" || f.type === "ref" || f.type === "date" ? null : f.type === "select" ? f.options![0][0] : "";
  return { ...d, ...extra };
}

/** Page CRUD générique : tableau + recherche + formulaire en fenêtre + export CSV. */
export function ResourcePage({
  title,
  subtitle,
  endpoint,
  fields,
  columns,
  newLabel,
  initial,
  searchable = true,
  exportName,
  headerExtra,
  rowActions,
  canWrite = true,
  empty,
  rowClass,
  formTop,
}: {
  title: string;
  subtitle?: string;
  endpoint: string;
  fields: FieldDef[];
  columns: Column[];
  newLabel: string;
  initial?: Record<string, unknown>;
  searchable?: boolean;
  exportName?: string;
  headerExtra?: ReactNode;
  rowActions?: (r: Row) => ReactNode;
  canWrite?: boolean;
  empty?: string;
  rowClass?: (r: Row) => string;
  formTop?: (patch: (values: Record<string, unknown>) => void) => ReactNode;
}) {
  const qc = useQueryClient();
  const [q, setQ] = useState(() => new URLSearchParams(window.location.search).get("q") ?? "");
  const [edit, setEdit] = useState<Row | "new" | null>(null);
  const list = useQuery({ queryKey: ["res", endpoint, q], queryFn: () => api<Row[]>(`${endpoint}?q=${encodeURIComponent(q)}`) });
  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => (edit && edit !== "new" ? api(`${endpoint}/${edit.id}`, "PUT", body) : api(endpoint, "POST", body)),
    onSuccess: () => {
      qc.invalidateQueries();
      setEdit(null);
    },
  });
  const del = useMutation({ mutationFn: (id: number) => api(`${endpoint}/${id}`, "DELETE"), onSuccess: () => qc.invalidateQueries() });
  return (
    <>
      <PageHeader
        title={title}
        subtitle={subtitle}
        action={
          <div className="flex gap-2">
            {exportName && <Button variant="ghost" onClick={() => downloadFile(`${endpoint}/export/csv`, `${exportName}.csv`)}>Exporter (CSV)</Button>}
            {canWrite && (
              <Button
                onClick={() => {
                  save.reset();
                  setEdit("new");
                }}
              >
                + {newLabel}
              </Button>
            )}
          </div>
        }
      />
      {headerExtra}
      <Card>
        {searchable && (
          <div className="mb-4 max-w-sm"><input placeholder="Rechercher…" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        )}
        {list.isLoading ? (
          <Loading />
        ) : !list.data?.length ? (
          <Empty>{empty ?? "Rien ici pour l'instant."}</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[600px] text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left text-xs uppercase text-slate-400">
                  {columns.map((c) => (
                    <th key={c.label} className={cx("py-2 pr-4", c.right && "text-right")}>{c.label}</th>
                  ))}
                  <th />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {list.data.map((r) => (
                  <tr key={r.id} className={rowClass?.(r)}>
                    {columns.map((c) => (
                      <td key={c.label} className={cx("py-2.5 pr-4", c.right && "text-right")}>{c.render(r)}</td>
                    ))}
                    <td className="space-x-3 whitespace-nowrap text-right text-xs">
                      {rowActions?.(r)}
                      {canWrite && (
                        <button
                          className="text-brand-600"
                          onClick={() => {
                            save.reset();
                            setEdit(r);
                          }}
                        >
                          Modifier
                        </button>
                      )}
                      {canWrite && (
                        <button className="text-red-600" onClick={() => confirm("Supprimer définitivement ?") && del.mutate(r.id)}>Supprimer</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="mt-3"><ErrorMsg error={del.error} /></div>
      </Card>
      {edit && (
        <FormModal
          title={edit === "new" ? newLabel : "Modifier"}
          fields={fields}
          initial={edit === "new" ? defaults(fields, initial) : edit}
          onClose={() => setEdit(null)}
          onSubmit={(b) => save.mutate(b)}
          busy={save.isPending}
          error={save.error}
          top={formTop}
        />
      )}
    </>
  );
}
