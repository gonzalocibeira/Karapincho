// SPDX-License-Identifier: GPL-3.0-or-later
import { useEffect, useState } from "react";
import { Activity, ArrowDownToLine, LoaderCircle, Play, X } from "lucide-react";

type Timing = { seconds: number; stages: Record<string, number> };
type Fixture = { language: string; title: string; duration: number; cpu: Timing; gpu: Timing };
type Latest = {
  status: string; mode?: string; error?: string;
  hardware?: { chip: string; architecture: string; os: string; memory_gb: number };
  progress?: { completed: number; total: number; stage?: string; title?: string; run?: number; software_matches?: boolean };
  rows?: { language: string; run: number; elapsed_seconds: number; stages: Record<string, {
    runtime: { backend?: string }; attempts: { status: string }[];
  }> }[];
  comparison?: { reference_mode: string; ratio: number | null; fixtures: (Timing & { language: string; ratio: number })[] };
};
type Data = { baseline: { hardware: string; os: string; fixtures: Fixture[] }; latest: Latest };
const seconds = (n: number) => `${n.toFixed(2)} s`;
const languages: Record<string, string> = { es: "Spanish", ja: "Japanese", en: "English" };
const stages: Record<string, string> = { prepare: "Media", separate: "Vocals", transcribe: "Transcription", align: "Alignment", pitch: "Pitch", chart: "Chart", package: "Export" };

export function Benchmark({ post }: { post: (url: string, body?: object) => Promise<unknown> }) {
  const [data, setData] = useState<Data | null>(null);
  const [mode, setMode] = useState("auto");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let disposed = false;
    const refresh = async () => {
      try {
        const response = await fetch("/api/benchmarks");
        if (!response.ok) throw new Error("Cannot load benchmarks. Restart Karapincho to load the updated app.");
        const value = await response.json();
        if (!disposed) { setData(value); setError(""); }
      } catch (e) { if (!disposed) setError(e instanceof Error ? e.message : "Cannot load benchmarks."); }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2000);
    return () => { disposed = true; clearInterval(timer); };
  }, []);
  async function action(cancel = false) {
    setBusy(true); setError("");
    try {
      const latest = await post(cancel ? "/api/benchmarks/cancel" : "/api/benchmarks", { mode }) as Latest;
      setData(current => current && { ...current, latest });
    } catch (e) { setError(e instanceof Error ? e.message : "Could not start benchmark."); }
    finally { setBusy(false); }
  }
  const latest = data?.latest;
  const active = latest && ["queued", "running", "cancelling"].includes(latest.status);
  return <section className="benchmark-page" aria-labelledby="benchmark-title">
    <p className="eyebrow">MEASURE YOUR MAC</p>
    <h1 id="benchmark-title">Benchmarks<span>.</span></h1>
    <p className="subtitle">See how this Mac compares with our M2 baseline using the same three songs.</p>
    {error && <p role="alert" className="job-error">{error}</p>}
    {data && <>
      <div className="benchmark-card">
        <div className="benchmark-heading"><Activity size={24} /><div><h2>{data.baseline.hardware}</h2><p>{data.baseline.os} · Three runs per song · Median processing time</p></div></div>
        <div className="benchmark-table-scroll"><table><thead><tr><th>Reference song</th><th>Song length</th><th>M2 CPU</th><th>M2 accelerated</th><th>Speedup</th></tr></thead>
          <tbody>{data.baseline.fixtures.map(f => <tr key={f.language}><th>{f.title}<small>{languages[f.language]}</small></th><td>{seconds(f.duration)}</td><td>{seconds(f.cpu.seconds)}</td><td>{seconds(f.gpu.seconds)}</td><td>{(f.cpu.seconds / f.gpu.seconds).toFixed(2)}×</td></tr>)}</tbody></table></div>
        <p className="benchmark-note">Cached models, fresh song outputs. Includes CPU recovery and process startup; excludes downloads and online lyric lookup. All accelerated reference runs used CPU transcription recovery for lyric quality. Desktop load and temperature were not controlled.</p>
        <details><summary>View M2 stage timings</summary><div className="benchmark-table-scroll"><table><thead><tr><th>Stage</th>{data.baseline.fixtures.map(f => <th key={f.language}>{languages[f.language]}<small>CPU / accelerated</small></th>)}</tr></thead><tbody>{Object.entries(stages).map(([stage, label]) => <tr key={stage}><th>{label}</th>{data.baseline.fixtures.map(f => <td key={f.language}>{seconds(f.cpu.stages[stage])} / {seconds(f.gpu.stages[stage])}</td>)}</tr>)}</tbody></table></div></details>
      </div>
      <div className="benchmark-card">
        <h2>Benchmark this Mac</h2>
        <p>Nine fresh runs: three each in Spanish, Japanese, and English. Allow around 25 minutes with acceleration on an M2, or longer on CPU. Keep your Mac plugged in and close other heavy apps.</p>
        <p className="benchmark-note">Starts after the current song. Queued songs wait until it finishes. Samples are bundled; models must already be cached by Setup. Your library stays available.</p>
        <div className="benchmark-controls"><label>Processing mode<select value={mode} onChange={e => setMode(e.target.value)} disabled={!!active || busy}><option value="auto">Automatic acceleration</option><option value="cpu">CPU only</option></select></label>
          <button className="create-button" onClick={() => void action()} disabled={!!active || busy}><Play size={16} />{busy ? "Starting…" : "Run benchmark"}</button>
          {active && <button className="quit-button" disabled={busy || latest?.status === "cancelling"} onClick={() => void action(true)}><X size={16} />Cancel benchmark</button>}
        </div>
        {latest && latest.status !== "idle" && <div className="benchmark-result" aria-live="polite">
          <h3>{active && <LoaderCircle size={16} className="spin" />} {({ queued: "Waiting for the current song", running: "Benchmark running", cancelling: "Stopping safely…", completed: "Benchmark complete", cancelled: "Benchmark cancelled", interrupted: "Benchmark interrupted", failed: "Benchmark failed" } as Record<string, string>)[latest.status]}</h3>
          {latest.hardware && <p>{latest.hardware.chip} · {latest.hardware.memory_gb} GB · {latest.mode === "cpu" ? "CPU only" : "Automatic acceleration"}</p>}
          {latest.progress && <><progress max={9} value={latest.rows?.length || 0} aria-label="Completed benchmark runs" /><p>{latest.rows?.length || 0} of 9 runs complete{active && latest.progress.title ? ` · ${latest.progress.title} · Run ${latest.progress.run} of 3 · ${stages[latest.progress.stage || ""] || "Preparing"}` : ""}</p></>}
          {latest.error && <p className="job-error">{latest.error}</p>}
          {latest.progress?.software_matches === false && <p className="benchmark-note">Software versions or processing settings differ from the baseline. Treat this as a system comparison, not a pure hardware comparison.</p>}
          {latest.comparison?.ratio != null && <p className="benchmark-score">{latest.comparison.ratio.toFixed(2)}× <span>the M2 {latest.comparison.reference_mode === "cpu" ? "CPU" : "accelerated"} processing speed</span></p>}
          <p className="benchmark-note">1.00× matches the M2; above 1.00× is faster. Scores use the sum of each song’s median time. Timing alone does not establish lyric or pitch accuracy.</p>
          {!!latest.comparison?.fixtures.length && <div className="benchmark-table-scroll"><table><thead><tr><th>Song</th><th>This Mac median</th><th>Compared with M2</th></tr></thead><tbody>{latest.comparison.fixtures.map(f => <tr key={f.language}><th>{languages[f.language]}</th><td>{seconds(f.seconds)}</td><td>{f.ratio.toFixed(2)}×</td></tr>)}</tbody></table></div>}
          {!!latest.rows?.length && <details><summary>Individual runs and actual backends</summary>{latest.rows.map(r => <p key={`${r.language}-${r.run}`}><strong>{languages[r.language]} · Run {r.run}: {seconds(r.elapsed_seconds)}</strong><br />{Object.entries(r.stages).map(([name, s]) => `${stages[name]}: ${s.runtime.backend || "CPU"}${s.attempts.length > 1 ? ` (${s.attempts.length} attempts)` : ""}`).join(" · ")}</p>)}</details>}
          <a className="report-link" href="/api/benchmarks/report"><ArrowDownToLine size={15} /> Download benchmark report</a>
        </div>}
      </div>
      <p className="benchmark-note">Reference recordings: La Cucaracha — Elisa, Sean Buss, Kenmayer; Sakura Sakura — Kanohara and an anonymous synthesized vocalist (both CC BY-SA 3.0). Auld Lang Syne — Frank C. Stanley (public domain). See the bundled attribution for sources.</p>
    </>}
  </section>;
}
