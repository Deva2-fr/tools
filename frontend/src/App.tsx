import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { ApiError, User, api, isManager } from "./api";
import Access from "./pages/Access";
import Alerts from "./pages/Alerts";
import Billing from "./pages/Billing";
import BillingEditor from "./pages/BillingEditor";
import Dashboard from "./pages/Dashboard";
import Documents from "./pages/Documents";
import Expenses from "./pages/Expenses";
import Login from "./pages/Login";
import MailPage from "./pages/Mail";
import ProjectDetail from "./pages/ProjectDetail";
import Projects from "./pages/Projects";
import PublicStatus from "./pages/PublicStatus";
import Renewals from "./pages/Renewals";
import Settings from "./pages/Settings";
import Taxes from "./pages/Taxes";
import { Employees } from "./pages/Team";
import Profile from "./pages/Profile";
import Time from "./pages/Time";
import Treasury from "./pages/Treasury";
import CompanyDetail from "./pages/crm/CompanyDetail";
import Companies from "./pages/crm/Companies";
import Contacts from "./pages/crm/Contacts";
import Pipeline from "./pages/crm/Pipeline";
import Tasks from "./pages/crm/Tasks";
import Tour from "./tour/Tour";
import { TOURS, markTourSeen, tourKey, tourSeen } from "./tour/tours";
import { Loading, cx } from "./ui";

interface NavItem { to: string; label: string; end?: boolean; manager?: boolean }
const SECTIONS: { title: string; items: NavItem[] }[] = [
  { title: "", items: [{ to: "/", label: "Tableau de bord", end: true }] },
  { title: "Commercial", items: [
    { to: "/crm/societes", label: "Sociétés" }, { to: "/crm/contacts", label: "Contacts" },
    { to: "/crm/pipeline", label: "Pipeline" }, { to: "/crm/taches", label: "Tâches" },
    { to: "/mails", label: "Mails" } ] },
  { title: "Finances", items: [
    { to: "/facturation", label: "Devis & factures", manager: true }, { to: "/tresorerie", label: "Trésorerie", manager: true },
    { to: "/abonnements", label: "Abonnements & contrats", manager: true }, { to: "/notes-de-frais", label: "Notes de frais" },
    { to: "/impots", label: "Impôts & TVA" } ] },
  { title: "Équipe", items: [
    { to: "/temps", label: "Suivi du temps" },
    { to: "/equipe/collaborateurs", label: "Collaborateurs", manager: true }, { to: "/documents", label: "Documents", manager: true },
    { to: "/acces", label: "Registre des accès", manager: true } ] },
  { title: "Infrastructure", items: [{ to: "/projets", label: "Projets & serveurs" }, { to: "/alertes", label: "Alertes & sécurité" }] },
  { title: "", items: [{ to: "/parametres", label: "Paramètres" }] },
];

function SearchPalette({ user, onClose }: { user: User; onClose: () => void }) {
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<{ type: string; label: string; sub: string; to: string }[]>([]);
  const pages = SECTIONS.flatMap((s) => s.items).filter((i) => (!i.manager || isManager(user)) && q.length > 0 && i.label.toLowerCase().includes(q.toLowerCase()));
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  useEffect(() => {
    if (q.trim().length < 2) { setHits([]); return; }
    const t = setTimeout(() => api<typeof hits>(`/crm/search?q=${encodeURIComponent(q)}`).then(setHits).catch(() => setHits([])), 200);
    return () => clearTimeout(t);
  }, [q]);
  const go = (to: string) => { nav(to); onClose(); };
  return (
    <div className="fixed inset-0 z-[60] flex items-start justify-center bg-slate-900/40 p-4 pt-24" onMouseDown={onClose}>
      <div className="w-full max-w-xl overflow-hidden rounded-md bg-white shadow-lg" onMouseDown={(e) => e.stopPropagation()}>
        <input autoFocus placeholder="Rechercher une société, un contact, une page…" className="!rounded-none !border-0 !border-b !py-4 !text-base !shadow-none" value={q} onChange={(e) => setQ(e.target.value)} />
        <ul className="max-h-80 overflow-y-auto py-1 text-sm">
          {pages.map((p) => <li key={p.to}><button className="flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-brand-50" onClick={() => go(p.to)}>{p.label}<span className="ml-auto text-xs text-slate-400">Page</span></button></li>)}
          {hits.map((h, i) => <li key={i}><button className="flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left hover:bg-brand-50" onClick={() => go(h.to)}><span><b>{h.label}</b> <span className="text-slate-400">{h.sub}</span></span><span className="text-xs text-slate-400">{h.type}</span></button></li>)}
          {q.length >= 2 && !pages.length && !hits.length && <li className="px-4 py-6 text-center text-slate-400">Aucun résultat</li>}
          {!q && <li className="px-4 py-6 text-center text-slate-400">Tapez pour chercher. <kbd className="rounded bg-slate-100 px-1.5">Échap</kbd> pour fermer.</li>}
        </ul>
      </div>
    </div>
  );
}

function Shell() {
  const qc = useQueryClient();
  const [searching, setSearching] = useState(false);
  const [menu, setMenu] = useState(false); // tiroir de navigation (mobile / tablette)
  const { pathname } = useLocation();
  useEffect(() => setMenu(false), [pathname]);
  useEffect(() => {
    if (!menu) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setMenu(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menu]);
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<User>("/auth/me"), retry: false });
  // Guide interactif : celui d'accueil la toute première fois, puis celui de chaque section à sa 1re visite.
  const [tour, setTour] = useState<string | null>(null);
  const uid = me.data?.id;
  useEffect(() => {
    if (!uid || tour) return;
    const key = !tourSeen("welcome", uid) ? "welcome" : tourKey(pathname);
    if (!key || tourSeen(key, uid)) return;
    const t = window.setTimeout(() => { markTourSeen(key, uid); setTour(key); }, 1200); // laisse la page se charger
    return () => window.clearTimeout(t);
  }, [uid, pathname, tour]);
  const startGuide = () => { setMenu(false); setTour(tourKey(pathname) ?? "welcome"); };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setSearching((s) => !s); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (me.isLoading) return <Loading />;
  if (me.error instanceof ApiError && me.error.status === 401) return <Login />;
  if (me.error) return <p className="p-10 text-center text-red-600">Impossible de joindre le serveur. Réessayez dans un instant.</p>;
  const user = me.data!;
  const mgr = isManager(user);
  const logout = async () => { await api("/auth/logout", "POST"); qc.clear(); window.location.href = "/"; };

  return (
    <div className="min-h-screen lg:flex">
      {/* Barre du haut : mobile et tablette */}
      <header className="sticky top-0 z-30 flex h-14 items-center gap-3 bg-[#1d2421] px-4 text-stone-200 lg:hidden">
        <button data-tour="nav" onClick={() => setMenu(true)} className="-ml-1 rounded p-1.5 text-xl leading-none hover:bg-white/10" aria-label="Ouvrir le menu">☰</button>
        <Link to="/" className="font-serif text-lg font-semibold tracking-tight text-stone-50">Deva2</Link>
        <button data-tour="search" onClick={() => setSearching(true)} className="ml-auto rounded border border-stone-700 px-3 py-1 text-sm text-stone-400" aria-label="Rechercher">Rechercher…</button>
        <button data-tour="guide" onClick={startGuide} className="rounded-full border border-stone-600 px-2.5 py-0.5 text-sm font-semibold text-stone-300" aria-label="Guide de la page" title="Guide de la page">?</button>
      </header>
      {menu && <div className="fixed inset-0 z-40 bg-black/50 lg:hidden" onClick={() => setMenu(false)} />}
      <aside className={cx("fixed inset-y-0 left-0 z-50 flex w-72 max-w-[85vw] flex-col overflow-y-auto bg-[#1d2421] text-stone-300 transition-transform lg:sticky lg:top-0 lg:z-auto lg:h-screen lg:w-60 lg:translate-x-0 lg:shrink-0 lg:transition-none", menu ? "translate-x-0" : "-translate-x-full")}>
        <div className="flex items-start justify-between px-5 pb-4 pt-6">
          <div>
            <p className="font-serif text-xl font-semibold tracking-tight text-stone-50">Deva2</p>
            <p className="text-xs text-stone-500">Gestion & outils internes</p>
          </div>
          <button onClick={() => setMenu(false)} className="text-stone-400 hover:text-white lg:hidden" aria-label="Fermer le menu">✕</button>
        </div>
        <button data-tour="search" onClick={() => setSearching(true)} className="mx-3 mb-2 hidden items-center justify-between rounded border border-stone-700 px-3 py-1.5 text-sm text-stone-400 hover:border-stone-500 lg:flex">
          <span>Rechercher…</span><kbd className="rounded bg-stone-800 px-1.5 text-xs text-stone-400">⌘K</kbd>
        </button>
        <button data-tour="guide" onClick={startGuide} className="mx-3 mb-3 hidden items-center gap-2 rounded px-3 py-1 text-left text-xs text-stone-400 hover:bg-white/5 hover:text-stone-100 lg:flex">
          <span className="flex h-4 w-4 items-center justify-center rounded-full border border-stone-500 text-[10px] font-bold">?</span> Guide de cette page
        </button>
        <nav data-tour="nav" className="flex-1 space-y-5 px-3 pb-4">
          {SECTIONS.map((sec, i) => {
            const items = sec.items.filter((n) => !n.manager || mgr);
            return items.length ? (
              <div key={i}>
                {sec.title && <p className="mb-1 px-3 text-[10px] font-semibold uppercase tracking-[0.12em] text-stone-500">{sec.title}</p>}
                <div className="space-y-0.5">{items.map((n) => (
                  <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => cx("block border-l-2 px-3 py-2 text-sm transition lg:py-1.5", isActive ? "border-emerald-400 bg-white/5 font-medium text-white" : "border-transparent text-stone-400 hover:text-stone-100")}>{n.label}</NavLink>))}</div>
              </div>) : null;
          })}
        </nav>
        <div className="border-t border-stone-800 p-4 text-sm">
          <Link data-tour="profile" to="/profil" className="block truncate font-medium text-stone-100 hover:underline" title="Mon profil">{user.name || user.email}</Link>
          <p className="truncate text-xs text-stone-500">{user.email} · {user.role === "admin" ? "Admin" : user.role === "manager" ? "Manager" : "Membre"}</p>
          <button onClick={logout} className="mt-2 text-xs font-medium text-stone-400 hover:text-white">Se déconnecter</button>
        </div>
      </aside>
      <main className="min-w-0 flex-1 px-4 py-5 sm:px-6 lg:px-10 lg:py-8">
        <div className="mx-auto max-w-6xl">
          <Routes>
            <Route path="/" element={<Dashboard user={user} />} />
            <Route path="/crm/societes" element={<Companies />} />
            <Route path="/crm/societes/:id" element={<CompanyDetail />} />
            <Route path="/crm/contacts" element={<Contacts />} />
            <Route path="/crm/pipeline" element={<Pipeline />} />
            <Route path="/crm/taches" element={<Tasks user={user} />} />
            <Route path="/projets" element={<Projects />} />
            <Route path="/projets/:id" element={<ProjectDetail />} />
            <Route path="/alertes" element={<Alerts user={user} />} />
            <Route path="/mails" element={<MailPage user={user} />} />
            <Route path="/notes-de-frais" element={<Expenses user={user} />} />
            <Route path="/impots" element={<Taxes />} />
            <Route path="/temps" element={<Time user={user} />} />
            <Route path="/parametres" element={<Settings user={user} />} />
            <Route path="/profil" element={<Profile me={user} />} />
            <Route path="/profil/:id" element={<Profile me={user} />} />
            {mgr && <>
              <Route path="/facturation" element={<Billing />} />
              <Route path="/facturation/nouveau" element={<BillingEditor />} />
              <Route path="/facturation/:id" element={<BillingEditor />} />
              <Route path="/tresorerie" element={<Treasury />} />
              <Route path="/abonnements" element={<Renewals />} />
              <Route path="/equipe/collaborateurs" element={<Employees />} />
              <Route path="/documents" element={<Documents />} />
              <Route path="/acces" element={<Access />} />
            </>}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
      </main>
      {searching && <SearchPalette user={user} onClose={() => setSearching(false)} />}
      {tour && TOURS[tour] && <Tour key={tour} steps={TOURS[tour]} onClose={() => setTour(null)} />}
    </div>
  );
}

export default function App() {
  const { pathname } = useLocation();
  return pathname === "/statut" ? <PublicStatus /> : <Shell />;
}
