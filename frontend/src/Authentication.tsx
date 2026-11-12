import { useState, type FormEvent } from "react";
import { ShieldCheck, ArrowUpRight } from "lucide-react";
import { api, setCsrf } from "./api";
import type { AuthResponse, User } from "./types";
export function Authentication({ onLogin, initialError = "" }: { onLogin: (user: User) => void; initialError?: string }) {
  const [error, setError] = useState(initialError),
    [busy, setBusy] = useState(false);
  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      const current = await api<AuthResponse>("/auth/me");
      setCsrf(current.csrf_token);
      const result = await api<AuthResponse>("/auth/login", {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(form)),
      });
      setCsrf(result.csrf_token);
      if (result.user) onLogin(result.user);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="signin">
      <div className="brand">
        <ShieldCheck />
        SafeSight<span>OPERATIONS</span>
      </div>
      <h1>
        A clearer view
        <br />
        of workplace safety.
      </h1>
      <p>Sign in with your invited Supabase account.</p>
      <form onSubmit={login}>
        <label>
          Email
          <input name="email" type="email" autoComplete="username" required />
        </label>
        <label>
          Password
          <input
            name="password"
            type="password"
            autoComplete="current-password"
            required
          />
        </label>
        <button disabled={busy}>
          {busy ? "Signing in?" : "Sign in"} <ArrowUpRight size={18} />
        </button>
      </form>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
    </main>
  );
}
