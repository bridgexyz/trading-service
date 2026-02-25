import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(username, password, totpCode);
      navigate("/", { replace: true });
    } catch (err: any) {
      setError(err.response?.data?.detail || "Login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-surface-0 p-4 relative overflow-hidden">
      {/* Background grid */}
      <div className="absolute inset-0 bg-grid opacity-30" />
      {/* Gradient orbs */}
      <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-accent/5 rounded-full blur-3xl" />
      <div className="absolute bottom-1/4 right-1/4 w-64 h-64 bg-accent/3 rounded-full blur-3xl" />

      <div className="w-full max-w-sm relative z-10 animate-fade-up">
        <div className="bg-surface-1/90 backdrop-blur-xl border border-border-default rounded-2xl p-7 space-y-6 shadow-2xl shadow-black/30">
          {/* Logo */}
          <div className="flex flex-col items-center gap-3 mb-2">
            <div className="w-12 h-12 rounded-xl bg-accent/8 border border-accent/15 flex items-center justify-center glow-accent">
              <svg width="22" height="22" viewBox="0 0 16 16" fill="none">
                <path d="M2 14L8 2L14 14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-accent" />
                <path d="M5 9.5H11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" className="text-accent" />
              </svg>
            </div>
            <div className="text-center">
              <h1 className="text-lg font-semibold tracking-tight text-text-primary">
                LIGHTER TRADE
              </h1>
              <p className="text-[10px] font-mono text-text-muted tracking-[0.3em] mt-0.5">
                AUTHENTICATE
              </p>
            </div>
          </div>

          {error && (
            <div className="bg-negative/8 border border-negative/20 rounded-lg px-3.5 py-2.5 text-negative text-[12px] font-mono">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="text-[10px] text-text-muted uppercase tracking-[0.15em] block mb-1.5 font-mono">
                Username
              </label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                autoComplete="username"
                className="w-full bg-surface-2/80 border border-border-default rounded-lg px-3.5 py-2.5 text-[13px] text-text-primary placeholder:text-text-muted hover:border-border-hover focus:border-accent/40 focus:outline-none transition-all"
              />
            </div>
            <div>
              <label className="text-[10px] text-text-muted uppercase tracking-[0.15em] block mb-1.5 font-mono">
                Password
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="current-password"
                className="w-full bg-surface-2/80 border border-border-default rounded-lg px-3.5 py-2.5 text-[13px] text-text-primary placeholder:text-text-muted hover:border-border-hover focus:border-accent/40 focus:outline-none transition-all"
              />
            </div>
            <div>
              <label className="text-[10px] text-text-muted uppercase tracking-[0.15em] block mb-1.5 font-mono">
                2FA Code
              </label>
              <input
                type="text"
                inputMode="numeric"
                pattern="[0-9]{6}"
                maxLength={6}
                value={totpCode}
                onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, ""))}
                required
                autoComplete="one-time-code"
                placeholder="------"
                className="w-full bg-surface-2/80 border border-border-default rounded-lg px-3.5 py-3 text-base font-mono text-text-primary placeholder:text-text-muted/30 hover:border-border-hover focus:border-accent/40 focus:outline-none transition-all tracking-[0.5em] text-center"
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="w-full bg-accent/90 hover:bg-accent text-surface-0 px-4 py-3 rounded-lg text-[13px] font-semibold transition-all disabled:opacity-50 min-h-[44px] tracking-wide shadow-lg shadow-accent/10 hover:shadow-accent/20"
            >
              {loading ? "Authenticating..." : "Enter Terminal"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
