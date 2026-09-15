// SPDX-License-Identifier: GPL-3.0-or-later
import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowDownToLine,
  ArrowRight,
  AudioLines,
  Check,
  ChevronDown,
  CircleHelp,
  Clock3,
  Disc3,
  FileVideo,
  FolderOpen,
  Globe2,
  HardDrive,
  Info,
  Link2,
  LoaderCircle,
  Mic2,
  Music2,
  Plus,
  Power,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  Trash2,
  Upload,
  X,
  AlertTriangle,
} from "lucide-react";
import "./style.css";
import { Benchmark } from "./Benchmark";

type LyricSettings = { title: string; artist: string; language: string; lyrics: string };
const emptyLyrics: LyricSettings = { title: "", artist: "", language: "", lyrics: "" };

type Job = {
  lyric_settings?: LyricSettings;
  lyric_source?: string;
  id: string;
  title: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  stage: string;
  progress: number;
  warnings: string[];
  error: string | null;
  created: number;
  elapsed_seconds: number | null;
  started_at: number | null;
  cancel_requested: boolean;
  source_type: string;
};
type Health = {
  version: string;
  shutting_down: boolean;
  ready: boolean;
  missing: string[];
  token: string;
  max_bytes: number;
};
const stages = [
  "acquire",
  "prepare",
  "lyrics",
  "separate",
  "transcribe",
  "align",
  "pitch",
  "chart",
  "package",
];
const labels: Record<string, string> = {
  acquire: "Getting your video",
  prepare: "Preparing audio & video",
  lyrics: "Finding lyrics online",
  separate: "Isolating the voice",
  transcribe: "Listening to the lyrics",
  align: "Syncing every word",
  pitch: "Finding the melody",
  chart: "Writing your song chart",
  package: "Packing it all up",
};

function Capybara() {
  return <img src="/logo.svg" alt="" aria-hidden="true" />;
}

function About({ version }: { version?: string }) {
  return <section className="about-page" aria-labelledby="about-title">
    <p className="eyebrow">ABOUT THE STUDIO</p>
    <div className="about-hero">
      <span className="about-logo"><Capybara /></span>
      <div><h1 id="about-title">Karapincho<span>.</span></h1>
      <p className="subtitle">A calm companion for turning songs into singalongs.</p></div>
    </div>
    <div className="about-grid">
      <article className="about-card"><h2>What’s in the name?</h2><p>Karapincho combines <strong>karaoke</strong> with <strong>carpincho</strong>—the Spanish word for capybara. You bring the song, and your capybara studio companion handles the busy work.</p></article>
      <article className="about-card"><h2>Local, with clear boundaries</h2><p>Uploaded media and AI inference stay on this Mac. YouTube input contacts YouTube, lyric lookup sends song metadata—not audio—to LRCLIB, and setup downloads dependencies and models. Karapincho has no telemetry.</p></article>
      <article className="about-card"><h2>Open source</h2><p>Karapincho {version ? `v${version}` : ""} source code is licensed under GPL-3.0-or-later. You may use, study, modify, and redistribute it under the GPL. Downloaded model weights retain separate terms; the default Demucs weight is research-only. The software is provided without warranty.</p><a href="https://github.com/gonzalocibeira/Karapincho" target="_blank" rel="noreferrer">View source and license</a></article>
      <article className="about-card"><h2>AI-assisted development</h2><p>Karapincho was created by Gonzalo Cibeira with substantial assistance from AI tools across product design, implementation, testing, research, and documentation. Gonzalo directed the project and remains its maintainer.</p></article>
      <article className="about-card"><h2>Acknowledgements</h2><p>Karapincho builds on open-source media, speech, alignment, pitch, language, and karaoke projects. Their licenses remain their own.</p><a href="https://github.com/gonzalocibeira/Karapincho/blob/main/THIRD_PARTY_NOTICES.md" target="_blank" rel="noreferrer">Third-party notices</a></article>
    </div>
    <p className="about-note">Karapincho is not affiliated with YouTube, LRCLIB, UltraStar Deluxe, or UltraStar WorldParty. Only process media you are entitled to use.</p>
  </section>;
}

function LyricFields({ value, onChange, disabled = false }: {
  value: LyricSettings; onChange: (value: LyricSettings) => void; disabled?: boolean;
}) {
  const [fileError, setFileError] = useState("");
  async function readLyrics(file?: File) {
    if (!file) return;
    setFileError("");
    if (!/\.(txt|lrc)$/i.test(file.name) || file.size > 300000) {
      setFileError("Choose a UTF-8 .txt or .lrc file smaller than 300 KB.");
      return;
    }
    try {
      const lyrics = await file.text();
      if (lyrics.length > 100000 || lyrics.includes("\uFFFD")) throw new Error("Use UTF-8 lyrics up to 100,000 characters.");
      onChange({ ...value, lyrics });
    } catch (error) { setFileError(error instanceof Error ? error.message : "Could not read lyrics."); }
  }
  return <fieldset className="lyric-fields" disabled={disabled}>
    <div className="lyric-metadata">
      <label>Song title<input value={value.title} maxLength={300} placeholder="Automatic"
        onChange={e => onChange({ ...value, title: e.target.value })} /></label>
      <label>Artist<input value={value.artist} maxLength={300} placeholder="Automatic"
        onChange={e => onChange({ ...value, artist: e.target.value })} /></label>
      <label>Language code<input value={value.language} maxLength={3} pattern="[a-z]{2,3}|"
        placeholder="Auto (ja, es, en…)" onChange={e => onChange({ ...value, language: e.target.value.toLowerCase() })} /></label>
    </div>
    <label>Lyrics (optional)<textarea rows={6} maxLength={100000} value={value.lyrics}
      placeholder="Paste original-language lyrics or timestamped LRC lyrics"
      onChange={e => onChange({ ...value, lyrics: e.target.value })} /></label>
    <label>Import lyrics<input type="file" accept=".txt,.lrc" onChange={e => void readLyrics(e.target.files?.[0])} /></label>
    {fileError && <p role="alert" className="job-error">{fileError}</p>}
    <p>We try LRCLIB automatically. Supplied lyrics take priority; Japanese is converted to romaji after syncing.</p>
  </fieldset>;
}

function LyricCorrection({ job, save }: { job: Job; save: (settings: LyricSettings) => Promise<void> }) {
  const [value, setValue] = useState<LyricSettings>({ ...emptyLyrics, ...job.lyric_settings });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  return <details className="lyric-options">
    <summary>Correct lyrics and rebuild</summary>
    <form onSubmit={async e => {
      e.preventDefault(); setSaving(true); setError("");
      try { await save(value); } catch (err) { setError(err instanceof Error ? err.message : "Rebuild failed."); }
      finally { setSaving(false); }
    }}>
      <LyricFields value={value} onChange={setValue} disabled={saving} />
      <p>Prepared audio and melody analysis are reused. The previous export stays on disk until the new package is ready.</p>
      {error && <p className="job-error" role="alert">{error}</p>}
      <button className="create-button" disabled={saving}>{saving ? "Queueing…" : "Rebuild with corrections"}</button>
    </form>
  </details>;
}

function App() {
  const [page, setPage] = useState<"studio" | "benchmarks" | "about">("studio");
  const [shutdown, setShutdown] = useState<"running" | "stopping" | "stopped">("running");
  const [now, setNow] = useState(Date.now() / 1000);
  const [deleting, setDeleting] = useState<string | null>(null);
  const deletedIds = useRef(new Set<string>());
  const [health, setHealth] = useState<Health | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [mode, setMode] = useState<"youtube" | "file">("youtube");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [error, setError] = useState("");
  const [lyricSettings, setLyricSettings] = useState<LyricSettings>({ ...emptyLyrics });
  const [connection, setConnection] = useState("");
  const [filter, setFilter] = useState("all");
  const [help, setHelp] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const compose = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (shutdown !== "running") return;
    let disposed = false;
    const refresh = async () => {
      try {
        const [h, j] = await Promise.all([
          fetch("/api/health"),
          fetch("/api/jobs"),
        ]);
        if (!h.ok || !j.ok)
          throw new Error(
            "Connection lost. Keep Start.command running; your songs are saved.",
          );
        const [healthData, jobData] = await Promise.all([h.json(), j.json()]);
        if (!disposed) {
          setHealth(healthData);
          if (healthData.shutting_down) setShutdown("stopping");
          setJobs(jobData.filter((job: Job) => !deletedIds.current.has(job.id)));
          setConnection("");
        }
      } catch {
        if (!disposed)
          setConnection(
            "Cannot reach the local app. Keep Start.command running; your songs are saved.",
          );
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2000);
    return () => {
      disposed = true;
      clearInterval(timer);
    };
  }, [shutdown]);

  useEffect(() => {
    if (shutdown !== "stopping") return;
    let disposed = false;
    const timer = window.setInterval(async () => {
      try {
        await fetch("/api/health", { signal: AbortSignal.timeout(3000) });
      } catch {
        if (!disposed) setShutdown("stopped");
      }
    }, 1000);
    return () => { disposed = true; clearInterval(timer); };
  }, [shutdown]);

  async function quitApp() {
    if (!window.confirm("Quit Karapincho? Any song in progress will stop and resume from its last completed stage when you reopen the app.")) return;
    setShutdown("stopping");
    setError("");
    try {
      await post("/api/shutdown");
    } catch (e) {
      setShutdown("running");
      setError(e instanceof Error ? e.message : "Could not shut down Karapincho.");
    }
  }

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(timer);
  }, []);

  async function deleteSong(job: Job) {
    if (!window.confirm(`Permanently delete “${job.title}” from disk? This erases its song folder, uploaded copy, generated files, and ZIP. Copies saved elsewhere are kept. This cannot be undone.`)) return;
    setDeleting(job.id);
    setError("");
    try {
      const response = await fetch(`/api/jobs/${job.id}`, {
        method: "DELETE",
        headers: { "X-Karapincho-Token": health?.token || "" },
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not delete the song.");
      deletedIds.current.add(job.id);
      setJobs((current) => current.filter((j) => j.id !== job.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not delete the song.");
    } finally {
      setDeleting(null);
    }
  }

  async function post(path: string, body?: object) {
    const response = await fetch(path, {
      method: "POST",
      headers: {
        "X-Karapincho-Token": health?.token || "",
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await response.json();
    if (!response.ok)
      throw new Error(
        typeof data.detail === "string"
          ? data.detail
          : "Please check your input and try again.",
      );
    return data;
  }
  function chooseFile(next?: File) {
    setError("");
    if (!next) return;
    if (!next.name.toLowerCase().endsWith(".mp4")) {
      setError("Choose an MP4 video with an audio track.");
      return;
    }
    if (next.size > (health?.max_bytes || 2 * 1024 ** 3)) {
      setError("This video is larger than 2 GB. Please use a smaller MP4.");
      return;
    }
    setFile(next);
    setMode("file");
  }
  function uploadFile(selected: File): Promise<Job> {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/jobs/upload");
      xhr.setRequestHeader("X-Karapincho-Token", health?.token || "");
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable)
          setUploadProgress(Math.round((100 * e.loaded) / e.total));
      };
      xhr.onerror = () =>
        reject(new Error("Upload interrupted. Please try again."));
      xhr.onload = () => {
        try {
          const data = JSON.parse(xhr.responseText);
          xhr.status < 300
            ? resolve(data)
            : reject(new Error(data.detail || "Upload failed"));
        } catch {
          reject(
            new Error("Upload failed. Please check that the app is running."),
          );
        }
      };
      const form = new FormData();
      form.append("file", selected);
      form.append("lyric_settings", JSON.stringify(lyricSettings));
      xhr.send(form);
    });
  }
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    setUploadProgress(0);
    try {
      const job: Job =
        mode === "youtube"
          ? await post("/api/jobs/url", { url: url.trim(), lyric_settings: lyricSettings })
          : await uploadFile(file!);
      setJobs((current) => [job, ...current.filter((j) => j.id !== job.id)]);
      setLyricSettings({ ...emptyLyrics });
      setUrl("");
      setFile(null);
      setFilter("all");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create your song.");
    } finally {
      setBusy(false);
    }
  }
  async function action(id: string, name: string) {
    try {
      const job = await post(`/api/jobs/${id}/${name}`);
      if (job.id)
        setJobs((current) => current.map((j) => (j.id === job.id ? job : j)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    }
  }
  const completed = jobs.filter((j) => j.status === "completed").length;
  const active = jobs.filter(
    (j) => j.status === "queued" || j.status === "running",
  ).length;
  const visible = jobs.filter(
    (j) =>
      filter === "all" ||
      (filter === "ready"
        ? j.status === "completed"
        : ["queued", "running"].includes(j.status)),
  );

  if (shutdown !== "running") return (
    <div className="shutdown-screen" role="status" aria-live="polite">
      <Power size={36} />
      <h1>{shutdown === "stopped" ? "Karapincho is stopped." : "Karapincho is shutting down…"}</h1>
      <p>Your songs are saved. Unfinished songs resume from their last completed stage.</p>
      <p>You can close this tab. Open <strong>Start.command</strong> to run Karapincho again.</p>
    </div>
  );

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="Karapincho home">
          <span className="brand-icon">
            <Capybara />
          </span>
          karapincho<span className="brand-dot">.</span>
        </a>
        <div className="workspace-label">YOUR STUDIO</div>
        <button
          aria-label="Song studio"
          title="Song studio"
          className={`nav-item ${page === "studio" ? "selected" : ""}`}
          onClick={() => { setPage("studio"); compose.current?.scrollIntoView({ behavior: "smooth" }); }}
        >
          <AudioLines size={19} /> Song studio{" "}
          <span className="nav-count">{jobs.length}</span>
        </button>
        <button aria-label="Benchmarks" title="Benchmarks" className={`nav-item ${page === "benchmarks" ? "selected" : ""}`} onClick={() => setPage("benchmarks")}><Clock3 size={19} /> Benchmarks</button>
        <button aria-label="About" title="About" className={`nav-item ${page === "about" ? "selected" : ""}`} onClick={() => setPage("about")}><Info size={19} /> About</button>
        <div className="sidebar-note">
          <span className="note-icon">
            <Mic2 size={20} />
          </span>
          <h3>
            Good songs.
            <br />
            Great company.
          </h3>
          <p>
            You bring the song.
            <br />
            We’ll get it singalong-ready.
          </p>
          <div className="mini-wave">
            {[8, 16, 27, 13, 33, 22, 11, 30, 18, 10, 23, 14].map((h, i) => (
              <i key={i} style={{ height: h }} />
            ))}
          </div>
        </div>
        <div className="sidebar-bottom">
          <div>
            <span className="live-dot" /> Runs on your Mac
          </div>
          <p>Local inference · no telemetry.</p>
          <button onClick={() => setHelp(!help)}>
            <CircleHelp size={16} /> How it works
          </button>
        </div>
      </aside>
      <main>
        <header className="topbar">
          <span>
            {page === "benchmarks" ? "Benchmarks" : page === "about" ? "About" : "Song studio"} <span className="breadcrumb">/</span>{" "}
            <span className="muted">Overview</span>
          </span>
          <div className="topbar-actions">
          <div className="local-badge">
            <HardDrive size={14} /> LOCAL STUDIO <span className="live-dot" />
          </div>
          <button className="quit-button" disabled={!health || busy} onClick={() => void quitApp()}>
            <Power size={16} /> Quit Karapincho
          </button>
          </div>
        </header>
        <div className="content">
          {page === "benchmarks" ? <Benchmark post={post} /> : page === "about" ? <About version={health?.version} /> : <>
          <div className="page-heading">
            <div>
              <p className="eyebrow">FROM SONG TO SINGALONG</p>
              <h1>
                Your next karaoke night
                <br />
                starts here<span>.</span>
              </h1>
              <p className="subtitle">
                A video in. A ready-to-sing song out. Let AI handle the
                in-between.
              </p>
            </div>
            <div className="heading-art" aria-hidden="true">
              <div className="disc">
                <div className="disc-inner">
                  <Mic2 size={30} />
                </div>
              </div>
              <span className="art-star">✳</span>
              <span className="art-note">
                <Music2 size={23} />
              </span>
            </div>
          </div>
          {(connection || error) && (
            <div className="alert error" role="alert">
              <AlertTriangle size={18} />
              <span>{connection || error}</span>
              {error && (
                <button aria-label="Dismiss error" onClick={() => setError("")}>
                  <X size={16} />
                </button>
              )}
            </div>
          )}
          {health && !health.ready && (
            <div className="alert" role="status">
              <AlertTriangle size={18} />
              <span>
                Setup is incomplete: {health.missing.join(", ")}. Run Setup.command,
                then restart the app.
              </span>
            </div>
          )}
          {help && (
            <div className="help-panel">
              <button
                className="close-help"
                onClick={() => setHelp(false)}
                aria-label="Close help"
              >
                <X size={18} />
              </button>
              <h3>One input. The whole song package.</h3>
              <p>
                We extract audio, isolate vocals for analysis, find lyrics online and
                sync the lyrics, detect the melody, then create an UltraStar
                chart with the original audio, video, and cover.
              </p>
              <p>
                Spanish and English lyrics stay in their original language.
                Japanese lyrics become romaji. Copy the finished folder into
                your UltraStar WorldParty or Deluxe Songs folder.
              </p>
              <p>
                Setup downloads the AI models. Processing can take longer
                than the song itself. Difficult recordings may include accuracy
                notices; no editing is required. If YouTube blocks a download,
                use an MP4.
              </p>
            </div>
          )}
          <section className="creator-card" ref={compose}>
            <div className="card-heading">
              <span className="orange-icon">
                <Plus size={20} />
              </span>
              <div>
                <h2>Create a song</h2>
                <p>Choose your source. We’ll take it from here.</p>
              </div>
              <span className="step-label">01 — THE INPUT</span>
            </div>
            <form onSubmit={submit}>
              <details className="lyric-options">
                <summary>Song details and lyrics (optional)</summary>
                <LyricFields value={lyricSettings} onChange={setLyricSettings} disabled={busy} />
              </details>
              <div
                className="source-tabs"
                role="tablist"
                aria-label="Song source"
              >
                <button
                  type="button"
                  role="tab"
                  aria-selected={mode === "youtube"}
                  onClick={() => setMode("youtube")}
                  className={mode === "youtube" ? "active" : ""}
                >
                  <Link2 size={16} /> YouTube link
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={mode === "file"}
                  onClick={() => setMode("file")}
                  className={mode === "file" ? "active" : ""}
                >
                  <FileVideo size={16} /> Upload video
                </button>
              </div>
              {mode === "youtube" ? (
                <div className="url-area">
                  <label htmlFor="youtube-url">YOUTUBE VIDEO URL</label>
                  <div className="url-row">
                    <div className="url-input">
                      <Link2 size={20} />
                      <input
                        id="youtube-url"
                        type="url"
                        placeholder="https://www.youtube.com/watch?v=…"
                        value={url}
                        onChange={(e) => setUrl(e.target.value)}
                        required
                        autoComplete="off"
                        disabled={busy}
                      />
                    </div>
                    <button
                      className="create-button"
                      disabled={
                        busy || !url.trim() || !health?.ready || !!connection
                      }
                    >
                      {busy ? (
                        <LoaderCircle size={18} className="spin" />
                      ) : (
                        <Sparkles size={18} />
                      )}{" "}
                      {busy ? "Adding song…" : "Create song"}{" "}
                      {!busy && <ArrowRight size={17} />}
                    </button>
                  </div>
                  <p className="input-hint">
                    One song per link. Download blocked?{" "}
                    <button type="button" onClick={() => setMode("file")}>
                      Upload an MP4 instead <ArrowRight size={12} />
                    </button>
                  </p>
                </div>
              ) : (
                <div className="file-area">
                  <input
                    ref={input}
                    type="file"
                    accept=".mp4,video/mp4"
                    aria-label="Choose MP4 video"
                    onChange={(e) => chooseFile(e.target.files?.[0])}
                    hidden
                  />
                  <button
                    type="button"
                    className={`dropzone ${dragging ? "dragging" : ""}`}
                    onClick={() => !busy && input.current?.click()}
                    onDragOver={(e) => {
                      e.preventDefault();
                      setDragging(true);
                    }}
                    onDragLeave={() => setDragging(false)}
                    onDrop={(e) => {
                      e.preventDefault();
                      setDragging(false);
                      if (!busy) chooseFile(e.dataTransfer.files[0]);
                    }}
                  >
                    <Upload size={25} />
                    <strong>{file ? file.name : "Drop your video here"}</strong>
                    <span>
                      {file
                        ? `${(file.size / 1024 ** 2).toFixed(1)} MB · Click to choose another`
                        : "or click to browse · MP4 · Up to 2 GB / 20 minutes"}
                    </span>
                  </button>
                  <button
                    className="create-button file-submit"
                    disabled={busy || !file || !health?.ready || !!connection}
                  >
                    {busy ? (
                      <LoaderCircle size={18} className="spin" />
                    ) : (
                      <Sparkles size={18} />
                    )}{" "}
                    {busy ? `Uploading ${uploadProgress}%` : "Create song"}{" "}
                    {!busy && <ArrowRight size={17} />}
                  </button>
                </div>
              )}
            </form>
            <div className="creator-footer">
              <span>
                <ShieldCheck size={15} /> Local inference · no telemetry
              </span>
              <span>
                <Globe2 size={15} /> Español · English · 日本語 → Romaji
              </span>
              <span>
                <Check size={15} /> Original vocals kept
              </span>
            </div>
          </section>
          <div className="process-strip">
            <span className="small-eyebrow">AUTOMATICALLY YOURS</span>
            <div>
              <AudioLines size={17} /> Extract audio <ArrowRight size={13} />
              <Mic2 size={17} /> Sync lyrics & notes <ArrowRight size={13} />
              <FolderOpen size={17} /> Package for UltraStar
            </div>
          </div>
          <section className="library">
            <div className="library-title">
              <div>
                <h2>
                  Your songs <span>{jobs.length}</span>
                </h2>
                <p>A little less setup. A lot more singing.</p>
              </div>
              <span className="library-count">
                {completed} ready <span>·</span> {active} processing
              </span>
            </div>
            <div className="library-toolbar">
              <div className="library-tabs">
                {[
                  ["all", "All songs"],
                  ["ready", "Ready to sing"],
                  ["active", "In progress"],
                ].map(([value, label]) => (
                  <button
                    key={value}
                    className={filter === value ? "chosen" : ""}
                    onClick={() => setFilter(value)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <span className="sort-label">
                Newest first <ChevronDown size={13} />
              </span>
            </div>
            {visible.length === 0 ? (
              <div className="empty-state">
                <div className="empty-icon">
                  <Disc3 size={30} />
                  <span>
                    <Plus size={12} />
                  </span>
                </div>
                <h3>
                  {jobs.length
                    ? "Nothing here just yet"
                    : "Your first song is waiting to happen"}
                </h3>
                <p>
                  {jobs.length
                    ? "Songs will appear here as they move through your studio."
                    : "Paste a link or drop a video above. We’ll do the heavy lifting."}
                </p>
                <span className="format-pill">
                  .TXT <span>+</span> .MP3 <span>+</span> .MP4 <span>+</span>{" "}
                  COVER
                </span>
              </div>
            ) : (
              <div className="song-list">
                {visible.map((job) => (
                  <article key={job.id} className="song-card">
                    <div className={`song-icon ${job.status}`}>
                      <Music2 size={23} />
                    </div>
                    <div className="song-body">
                      <div className="song-heading">
                        <h3>{job.title}</h3>
                        <span className={`status ${job.status}`}>
                          {job.status === "completed" ? (
                            <Check size={12} />
                          ) : job.status === "running" ? (
                            <LoaderCircle size={12} className="spin" />
                          ) : (
                            <Clock3 size={12} />
                          )}{" "}
                          {job.status === "completed"
                            ? "Ready to sing"
                            : job.status === "running"
                              ? "Creating"
                              : job.status[0].toUpperCase() +
                                job.status.slice(1)}
                        </span>
                      </div>
                      <p className="song-meta">
                        {job.source_type === "youtube"
                          ? "YouTube"
                          : "MP4 upload"}{" "}
                        <span>·</span>{" "}
                        {new Date(job.created * 1000).toLocaleDateString(
                          undefined,
                          { month: "short", day: "numeric" },
                        )}
                        {job.status === "completed"
                          ? " · UltraStar package"
                          : ""}
                      </p>
                      {job.elapsed_seconds != null && job.status !== "queued" && (
                        <p className="song-timing">
                          <Clock3 size={13} />
                          {job.status === "running" ? "Elapsed" : "Total processing time"}: {formatElapsed(
                            job.elapsed_seconds + (job.started_at != null ? Math.max(0, now - job.started_at) : 0),
                          )}
                        </p>
                      )}
                      {job.status === "running" && (
                        <div className="job-progress">
                          <div className="progress-track" role="progressbar" aria-label={`${job.title} progress`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(job.progress * 100)}>
                            <span
                              style={{
                                width: `${Math.max(3, job.progress * 100)}%`,
                              }}
                            />
                          </div>
                          <p>
                            {job.cancel_requested
                              ? "Stopping safely…"
                              : labels[job.stage]}{" "}
                            <span>{stages.indexOf(job.stage) + 1} of {stages.length}</span>
                          </p>
                        </div>
                      )}
                      {job.status === "queued" && (
                        <p className="queued-note">
                          In line. Your Mac processes one song at a time.
                        </p>
                      )}
                      {job.lyric_source && <p className="song-meta">Lyrics: {{ lrclib: "LRCLIB", "lrclib+transcription": "LRCLIB + local transcription", user: "Supplied by you", transcription: "Local transcription" }[job.lyric_source] || job.lyric_source}</p>}
                      {["completed", "failed", "cancelled"].includes(job.status) && <LyricCorrection job={job} save={async settings => {
                        const updated = await post(`/api/jobs/${job.id}/rebuild`, settings);
                        setJobs(current => current.map(j => j.id === job.id ? updated : j));
                      }} />}
                      {job.error && <p className="job-error">{job.error}</p>}
                      {job.warnings.length > 0 && (
                        <details className="quality">
                          <summary>
                            <AlertTriangle size={13} /> {job.warnings.length}{" "}
                            quality{" "}
                            {job.warnings.length === 1 ? "notice" : "notices"}{" "}
                            <ChevronDown size={12} />
                          </summary>
                          <ul>
                            {job.warnings.map((w, i) => (
                              <li key={i}>{w}</li>
                            ))}
                          </ul>
                        </details>
                      )}
                    </div>
                    <div className="song-actions">
                      {job.status === "completed" ? (
                        <>
                          <a
                            className="download-button"
                            href={`/api/jobs/${job.id}/download`}
                          >
                            <ArrowDownToLine size={16} /> Download
                          </a>
                          <button
                            title="Open song folder"
                            aria-label={`Open folder for ${job.title}`}
                            onClick={() => void action(job.id, "open-folder")}
                          >
                            <FolderOpen size={18} />
                          </button>
                          <a
                            className="report-link"
                            href={`/api/jobs/${job.id}/report`}
                            target="_blank"
                            rel="noreferrer"
                          >
                            Report
                          </a>
                        </>
                      ) : ["queued", "running"].includes(job.status) ? (
                        <button
                          disabled={job.cancel_requested}
                          onClick={() => void action(job.id, "cancel")}
                        >
                          <X size={15} /> Cancel
                        </button>
                      ) : (
                        <button onClick={() => void action(job.id, "retry")}>
                          <RotateCcw size={15} /> Retry
                        </button>
                      )}
                      {["completed", "failed", "cancelled"].includes(job.status) && (
                        <button
                          className="delete-button"
                          aria-label={`Delete ${job.title} from disk`}
                          title="Permanently delete song from disk"
                          disabled={deleting !== null}
                          onClick={() => void deleteSong(job)}
                        >
                          <Trash2 size={15} /> {deleting === job.id ? "Deleting…" : "Delete"}
                        </button>
                      )}
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>
          </>}
          <footer className="page-footer">
            <span>Made for the songs you can’t help singing.</span>
            <span>
              UltraStar WorldParty & Deluxe{" "}
              <span className="footer-dot">●</span> Local AI{health?.version ? ` · v${health.version}` : ""}
            </span>
          </footer>
        </div>
      </main>
    </div>
  );
}

function formatElapsed(seconds: number) {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainder = total % 60;
  return hours ? `${hours}h ${minutes}m ${remainder}s` : `${minutes}m ${remainder}s`;
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
