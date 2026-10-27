import { useQuery } from "@tanstack/react-query";
import { cx } from "../ui";

/** Page publique /statut : sans connexion, n'affiche que le nom et l'état des services cochés « publics ». */
export default function PublicStatus() {
  const { data, isLoading } = useQuery({
    queryKey: ["public-status"],
    queryFn: async () => { const r = await fetch("/api/public/status"); if (!r.ok) throw new Error(); return r.json() as Promise<{ overall: string; services: { name: string; status: string }[] }>; },
    refetchInterval: 60_000,
  });
  const ok = data?.overall === "up", down = data?.overall === "down";
  return (
    <div className="mx-auto max-w-2xl px-4 py-12">
      <h1 className="mb-6 text-center text-2xl font-bold">État de nos services</h1>
      {isLoading || !data ? <p className="text-center text-slate-400">Chargement…</p> : (
        <>
          <div className={cx("mb-6 rounded-md p-5 text-center text-lg font-semibold", ok ? "bg-emerald-50 text-emerald-700" : down ? "bg-red-50 text-red-700" : "bg-slate-100 text-slate-600")}>
            {ok ? " Tous les services fonctionnent normalement" : down ? " Un ou plusieurs services sont perturbés" : "Aucune information disponible"}
          </div>
          <ul className="divide-y divide-slate-100 rounded-md border border-slate-200 bg-white">
            {data.services.map((s) => (
              <li key={s.name} className="flex items-center justify-between px-5 py-4">
                <span className="font-medium">{s.name}</span>
                <span className={cx("flex items-center gap-2 text-sm", s.status === "up" ? "text-emerald-800" : s.status === "down" ? "text-red-600" : "text-slate-400")}>
                  <span className={cx("h-2.5 w-2.5 rounded-full", s.status === "up" ? "bg-emerald-500" : s.status === "down" ? "bg-red-500" : "bg-slate-300")} />
                  {s.status === "up" ? "Opérationnel" : s.status === "down" ? "Indisponible" : "Inconnu"}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
