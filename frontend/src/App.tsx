import { useQuery, useQueryClient } from "@tanstack/react-query";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { ApiError, User, api } from "./api";
import Alerts from "./pages/Alerts";
import Dashboard from "./pages/Dashboard";
import Expenses from "./pages/Expenses";
import Login from "./pages/Login";
import MailPage from "./pages/Mail";
import ProjectDetail from "./pages/ProjectDetail";
import Projects from "./pages/Projects";
import Settings from "./pages/Settings";
import Taxes from "./pages/Taxes";
import { Loading, cx } from "./ui";

const NAV = [
  { to: "/", label: "Tableau de bord", icon: "🏠", end: true },
  { to: "/projets", label: "Projets & serveurs", icon: "🌐" },
  { to: "/alertes", label: "Alertes & sécurité", icon: "🚨" },
  { to: "/mails", label: "Mails Outlook", icon: "✉️" },
  { to: "/notes-de-frais", label: "Notes de frais", icon: "🧾" },
  { to: "/impots", label: "Impôts & TVA", icon: "📅" },
  { to: "/parametres", label: "Paramètres", icon: "⚙️" },
];

export default function App() {
  const qc = useQueryClient();
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api<User>("/auth/me"),
    retry: false,
  });

  if (me.isLoading) return <Loading />;
  if (me.error instanceof ApiError && me.error.status === 401) return <Login />;
  if (me.error) return <p className="p-10 text-center text-red-600">Impossible de joindre le serveur. Réessayez dans un instant.</p>;
  const user = me.data!;

  const logout = async () => {
    await api("/auth/logout", "POST");
    qc.clear();
    window.location.href = "/";
  };

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 flex h-screen w-64 shrink-0 flex-col border-r border-slate-200 bg-white">
        <div className="flex items-center gap-3 px-5 py-5">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-600 text-sm font-bold text-white">D2</span>
          <div>
            <p className="font-semibold leading-tight text-slate-900">Deva2 Hub</p>
            <p className="text-xs text-slate-400">Outils internes</p>
          </div>
        </div>
        <nav className="flex-1 space-y-1 px-3">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) =>
                cx("flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition", isActive ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-50")
              }
            >
              <span>{n.icon}</span>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-slate-100 p-4 text-sm">
          <p className="truncate font-medium text-slate-800">{user.name || user.email}</p>
          <p className="truncate text-xs text-slate-400">{user.email}</p>
          <button onClick={logout} className="mt-2 text-xs font-medium text-slate-500 hover:text-red-600">Se déconnecter</button>
        </div>
      </aside>
      <main className="min-w-0 flex-1 p-8">
        <div className="mx-auto max-w-6xl">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/projets" element={<Projects />} />
            <Route path="/projets/:id" element={<ProjectDetail />} />
            <Route path="/alertes" element={<Alerts user={user} />} />
            <Route path="/mails" element={<MailPage user={user} />} />
            <Route path="/notes-de-frais" element={<Expenses user={user} />} />
            <Route path="/impots" element={<Taxes />} />
            <Route path="/parametres" element={<Settings user={user} />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}
