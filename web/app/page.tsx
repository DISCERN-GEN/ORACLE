"use client";
import { useEffect, useState } from "react";

type AnyData = Record<string, any>;
const API = process.env.NEXT_PUBLIC_ORACLE_API_URL || "http://localhost:8000";

export default function Home() {
  const [token, setToken] = useState("");
  const [status, setStatus] = useState<AnyData | null>(null);
  const [markets, setMarkets] = useState<AnyData[]>([]);
  const [session, setSession] = useState<AnyData | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function api(path: string, method = "GET", body?: AnyData) {
    const res = await fetch(`${API}${path}`, {
      method, headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` },
      body: body ? JSON.stringify(body) : undefined, cache: "no-store"
    });
    const data = await res.json();
    if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data));
    return data;
  }

  async function refresh() {
    setBusy(true); setError("");
    try {
      const [s, m, p] = await Promise.all([api("/v1/system"), api("/v1/markets?limit=50"), api("/v1/paper/session")]);
      setStatus(s); setMarkets(m.data || []); setSession(p);
    } catch (e) { setError(e instanceof Error ? e.message : "Request failed"); }
    finally { setBusy(false); }
  }

  async function start() {
    setError("");
    try { await api("/v1/paper/session/start", "POST", { hours: 12 }); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not start session"); }
  }
  async function stop() {
    setError("");
    try { await api("/v1/paper/session/stop", "POST", { reason: "Stopped by owner from dashboard" }); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not stop session"); }
  }

  useEffect(() => { const saved = sessionStorage.getItem("oracle-token"); if (saved) setToken(saved); }, []);
  useEffect(() => { if (token) { sessionStorage.setItem("oracle-token", token); refresh(); } }, [token]);

  return <main className="shell">
    <header className="top"><div><div className="eyebrow">PRIVATE · SINGLE OWNER</div><h1>ORACLE</h1><p>Autonomous Prediction Market Intelligence &amp; Paper Execution</p></div><div className="mode">PAPER ONLY</div></header>
    <section className="panel auth"><label>Owner API token <input type="password" value={token} onChange={e => setToken(e.target.value)} placeholder="Paste ORACLE_API_TOKEN" /></label><button onClick={refresh} disabled={!token || busy}>{busy ? "Refreshing…" : "Connect / Refresh"}</button></section>
    {error && <div className="error">{error}</div>}
    <section className="grid">
      <article className="panel"><div className="eyebrow">SYSTEM MODE</div><h2>{status?.mode || "—"}</h2><p>{status?.deployment_type || "Connect to the local API"}</p></article>
      <article className="panel"><div className="eyebrow">LIVE EXECUTION</div><h2 className="off">DISABLED</h2><p>No wallet signing or real orders in this build.</p></article>
      <article className="panel"><div className="eyebrow">MARKETS RETURNED</div><h2>{markets.length}</h2><p>Public Gamma market metadata</p></article>
      <article className="panel"><div className="eyebrow">PAPER CASH</div><h2>{status?.paper_account?.cash ? Number(status.paper_account.cash).toLocaleString() : "—"}</h2><p>Simulated bankroll only</p></article>
    </section>
    <section className="panel session">
      <div><div className="eyebrow">12-HOUR AUTONOMOUS ACCEPTANCE TEST · LOCKED</div><h2>{status?.autonomous_acceptance_test_locked ? "Not yet authorised" : (session?.agent_state || "not started")}</h2><p>{status?.autonomous_acceptance_test_locked ? "This build is still under development. The test unlocks only after all wallet, market-data, forecasting, risk, execution and recovery gates pass." : (session?.session_id || "No active paper session")}</p><p>Observations: {session?.observations ?? 0} · Errors: {session?.errors ?? 0} · Simulated orders: {session?.orders_submitted ?? 0}</p></div>
      <div className="actions"><button onClick={start} disabled={!token || status?.autonomous_acceptance_test_locked || session?.agent_state === "running"}>Test locked</button><button className="secondary" onClick={stop} disabled={!token || session?.agent_state !== "running"}>Stop test</button></div>
    </section>
    <section className="panel"><div className="section-title"><div><div className="eyebrow">MARKET DISCOVERY</div><h2>Open market sample</h2></div><button className="secondary" onClick={refresh} disabled={!token || busy}>Refresh</button></div>
      <div className="table-wrap"><table><thead><tr><th>Question</th><th>Category</th><th>Close date</th><th>Liquidity</th></tr></thead><tbody>{markets.slice(0, 20).map((m, i) => <tr key={m.id || i}><td>{m.question || "Untitled market"}</td><td>{m.category || "—"}</td><td>{m.endDateIso || m.endDate || "—"}</td><td>{m.liquidityNum != null ? Number(m.liquidityNum).toLocaleString() : "—"}</td></tr>)}</tbody></table></div>
    </section>
    <footer>ORACLE v0.5 · Private local deployment · Paper execution only · All times UTC in the API</footer>
  </main>;
}
