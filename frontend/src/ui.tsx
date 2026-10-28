import { ReactNode, useEffect } from "react";

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

type BtnProps = React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "danger" | "soft"; busy?: boolean };
export function Button({ variant = "primary", busy, className, children, disabled, ...p }: BtnProps) {
  const styles = {
    primary: "bg-brand-600 text-white hover:bg-brand-700 border border-brand-700",
    soft: "bg-white text-brand-700 border border-brand-600/40 hover:bg-brand-50",
    ghost: "bg-transparent text-slate-700 border border-slate-300 hover:bg-slate-100",
    danger: "bg-transparent text-red-700 border border-red-300 hover:bg-red-50",
  }[variant];
  return (
    <button
      {...p}
      disabled={disabled || busy}
      className={cx("inline-flex items-center justify-center gap-2 rounded px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50", styles, className)}
    >
      {busy && <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />}
      {children}
    </button>
  );
}

export function Card({ title, action, children, className }: { title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cx("rounded-md border border-slate-200 bg-white", className)}>
      {(title || action) && (
        <header className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 border-b border-slate-200 px-4 py-3 sm:px-5">
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500">{title}</h2>
          {action}
        </header>
      )}
      <div className="p-4 sm:p-5">{children}</div>
    </section>
  );
}

export function PageHeader({ title, subtitle, action }: { title: string; subtitle?: string; action?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3 border-b border-slate-300 pb-4 sm:mb-6">
      <div className="min-w-0">
        <h1 className="break-words font-serif text-2xl font-semibold leading-tight text-slate-900 sm:text-[28px]">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
      </div>
      {action && <div className="flex min-w-0 max-w-full flex-wrap items-center gap-2">{action}</div>}
    </div>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-700">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-slate-400">{hint}</span>}
    </label>
  );
}

const tones = {
  green: "border-emerald-700/30 text-emerald-800",
  red: "border-red-700/30 bg-red-50/60 text-red-800",
  amber: "border-amber-700/30 bg-amber-50/60 text-amber-800",
  blue: "border-brand-600/30 text-brand-700",
  slate: "border-slate-300 text-slate-600",
};
export function Badge({ tone = "slate", children }: { tone?: keyof typeof tones; children: ReactNode }) {
  return <span className={cx("inline-flex items-center gap-1 rounded-sm border px-1.5 py-px text-xs font-medium", tones[tone])}>{children}</span>;
}

export function StatusDot({ status }: { status: string }) {
  const color = status === "up" ? "bg-emerald-500" : status === "down" ? "bg-red-500" : "bg-slate-300";
  const label = status === "up" ? "En ligne" : status === "down" ? "Hors ligne" : "Pas encore vérifié";
  return (
    <span className="inline-flex items-center gap-2 text-sm">
      <span className={cx("h-2.5 w-2.5 rounded-full", color, status === "down" && "animate-pulse")} />
      {label}
    </span>
  );
}

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/50 p-2 pt-4 sm:p-4 sm:pt-16" onMouseDown={onClose}>
      <div className={cx("w-full min-w-0 rounded-md bg-white shadow-lg", wide ? "max-w-2xl" : "max-w-lg")} onMouseDown={(e) => e.stopPropagation()}>
        <header className="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-3.5 sm:px-5">
          <h3 className="font-serif text-lg font-semibold text-slate-900">{title}</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700" aria-label="Fermer">✕</button>
        </header>
        <div className="p-4 sm:p-5">{children}</div>
      </div>
    </div>
  );
}

/** Tableau défilable horizontalement sur petit écran (la page, elle, ne déborde jamais). */
export function TableWrap({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx("-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0", className)}>{children}</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded border border-dashed border-slate-300 px-4 py-8 text-center text-sm text-slate-500">{children}</p>;
}

export function ErrorMsg({ error }: { error: unknown }) {
  if (!error) return null;
  return <p className="rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error instanceof Error ? error.message : String(error)}</p>;
}

export function Loading() {
  return <p className="py-10 text-center text-sm text-slate-400">Chargement…</p>;
}

export const fmtDate = (d?: string | null) => (d ? new Date(d.length === 10 ? d + "T12:00:00" : d).toLocaleDateString("fr-FR") : "—");
export const fmtDateTime = (d?: string | null) => (d ? new Date(d).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");
export const fmtMoney = (n?: number | null) => (n == null ? "—" : n.toLocaleString("fr-FR", { style: "currency", currency: "EUR" }));
