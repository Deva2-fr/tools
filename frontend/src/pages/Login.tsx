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
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-brand-50 to-slate-100 p-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-2xl bg-white p-8 shadow-xl">
        <div className="text-center">
          <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-brand-600 font-bold text-white">D2</span>
          <h1 className="mt-4 text-xl font-bold text-slate-900">Deva2 Hub</h1>
          <p className="text-sm text-slate-500">Connectez-vous pour continuer</p>
        </div>
        <Field label="E-mail">
          <input type="email" required autoFocus autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Mot de passe">
          <input type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        {needTotp && (
          <Field label="Code à 6 chiffres" hint="Ouvrez votre application d'authentification (Google Authenticator, Authy…)">
            <input inputMode="numeric" autoComplete="one-time-code" maxLength={6} required autoFocus value={totp} onChange={(e) => setTotp(e.target.value)} />
          </Field>
        )}
        <ErrorMsg error={error} />
        <Button type="submit" busy={busy} className="w-full">Se connecter</Button>
      </form>
    </div>
  );
}
