import { useState } from "react";
import { api } from "../api";
import { Button, ErrorMsg, Field } from "../ui";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [totp, setTotp] = useState("");
  const [needTotp, setNeedTotp] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/auth/login", "POST", { email, password, totp_code: totp || null });
      window.location.reload();
    } catch (err) {
      if (err instanceof Error && err.message === "totp_required") setNeedTotp(true);
      else setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid min-h-screen md:grid-cols-[1fr_440px]">
      <div className="hidden flex-col justify-between bg-[#1d2421] p-12 text-stone-300 md:flex">
        <p className="font-serif text-2xl font-semibold text-stone-50">Deva2</p>
        <div>
          <p className="max-w-sm font-serif text-3xl leading-snug text-stone-50">Clients, facturation, équipe et infrastructure au même endroit.</p>
          <p className="mt-4 text-sm text-stone-500">Accès réservé à l'équipe.</p>
        </div>
        <p className="text-xs text-stone-600">deva2.fr</p>
      </div>
      <div className="flex items-center justify-center p-8">
        <form onSubmit={submit} className="w-full max-w-xs space-y-4">
          <div>
            <h1 className="font-serif text-2xl font-semibold text-slate-900">Connexion</h1>
          </div>
          <Field label="Adresse e-mail">
            <input type="email" required autoFocus autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Field label="Mot de passe">
            <input type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </Field>
          {needTotp && (
            <Field label="Code à 6 chiffres" hint="Affiché par votre application d'authentification.">
              <input inputMode="numeric" autoComplete="one-time-code" maxLength={6} required autoFocus value={totp} onChange={(e) => setTotp(e.target.value)} />
            </Field>
          )}
          <ErrorMsg error={error} />
          <Button type="submit" busy={busy} className="w-full">Se connecter</Button>
        </form>
      </div>
    </div>
  );
}
