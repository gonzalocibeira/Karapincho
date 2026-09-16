// SPDX-License-Identifier: GPL-3.0-or-later
import React, { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowDownToLine,
  ArrowRight,
  AudioLines,
  Check,
  CircleHelp,
  Clock3,
  Disc3,
  FileVideo,
  FolderOpen,
  HardDrive,
  Info,
  Link2,
  LoaderCircle,
  Mic2,
  Music2,
  Plus,
  Power,
  RotateCcw,
  Sparkles,
  Trash2,
  Upload,
  X,
  AlertTriangle,
} from "lucide-react";
import "./style.css";
import { Benchmark } from "./Benchmark";

type LyricSettings = {
  title: string;
  artist: string;
  language: string;
  lyrics: string;
};
const emptyLyrics: LyricSettings = {
  title: "",
  artist: "",
  language: "",
  lyrics: "",
};

type Job = {
  processing_mode?: "quality" | "fast";
  export_receipt?: { path?: string; exported_at?: number };
  cleaned_at?: number | null;
  local_available?: boolean;
  activity?: string;

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
  return (
    <section className="about-page" aria-labelledby="about-title">
      <p className="eyebrow">ABOUT THE STUDIO</p>
      <div className="about-hero">
        <span className="about-logo">
          <Capybara />
        </span>
        <div>
          <h1 id="about-title">
            Karapincho<span>.</span>
          </h1>
          <p className="subtitle">
            A calm companion for turning songs into singalongs.
          </p>
        </div>
      </div>
      <div className="about-grid">
        <article className="about-card">
          <h2>What’s in the name?</h2>
          <p>
            Karapincho combines <strong>karaoke</strong> with{" "}
            <strong>carpincho</strong>—the Spanish word for capybara. You bring
            the song, and your capybara studio companion handles the busy work.
          </p>
        </article>
        <article className="about-card">
          <h2>Local, with clear boundaries</h2>
          <p>
            Uploaded media and AI inference stay on this Mac. YouTube input
            contacts YouTube, lyric lookup sends song metadata—not audio—to
            LRCLIB, and setup downloads dependencies and models. Karapincho has
            no telemetry.
          </p>
        </article>
        <article className="about-card">
          <h2>Open source</h2>
          <p>
            Karapincho {version ? `v${version}` : ""} source code is licensed
            under GPL-3.0-or-later. You may use, study, modify, and redistribute
            it under the GPL. Downloaded model weights retain separate terms;
            the default Demucs weight is research-only. The software is provided
            without warranty.
          </p>
          <a
            href="https://github.com/gonzalocibeira/Karapincho"
            target="_blank"
            rel="noreferrer"
          >
            View source and license
          </a>
        </article>
        <article className="about-card">
          <h2>AI-assisted development</h2>
          <p>
            Karapincho was created by Gonzalo Cibeira with substantial
            assistance from AI tools across product design, implementation,
            testing, research, and documentation. Gonzalo directed the project
            and remains its maintainer.
          </p>
        </article>
        <article className="about-card">
          <h2>Acknowledgements</h2>
          <p>
            Karapincho builds on open-source media, speech, alignment, pitch,
            language, and karaoke projects. Their licenses remain their own.
          </p>
          <a
            href="https://github.com/gonzalocibeira/Karapincho/blob/main/THIRD_PARTY_NOTICES.md"
            target="_blank"
            rel="noreferrer"
          >
            Third-party notices
          </a>
        </article>
      </div>
      <p className="about-note">
        Karapincho is not affiliated with YouTube, LRCLIB, UltraStar Deluxe, or
        UltraStar WorldParty. Only process media you are entitled to use.
      </p>
    </section>
  );
}

function LyricFields({
  value,
  onChange,
  disabled = false,
}: {
  value: LyricSettings;
  onChange: (value: LyricSettings) => void;
  disabled?: boolean;
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
      if (lyrics.length > 100000 || lyrics.includes("\uFFFD"))
        throw new Error("Use UTF-8 lyrics up to 100,000 characters.");
      onChange({ ...value, lyrics });
    } catch (error) {
      setFileError(
        error instanceof Error ? error.message : "Could not read lyrics.",
      );
    }
  }
  return (
    <fieldset className="lyric-fields" disabled={disabled}>
      <div className="lyric-metadata">
        <label>
          Song title
          <input
            value={value.title}
            maxLength={300}
            placeholder="Automatic"
            onChange={(e) => onChange({ ...value, title: e.target.value })}
          />
        </label>
        <label>
          Artist
          <input
            value={value.artist}
            maxLength={300}
            placeholder="Automatic"
            onChange={(e) => onChange({ ...value, artist: e.target.value })}
          />
        </label>
        <label>
          Language code
          <input
            value={value.language}
            maxLength={3}
            pattern="[a-z]{2,3}|"
            placeholder="Auto (ja, es, en…)"
            onChange={(e) =>
              onChange({ ...value, language: e.target.value.toLowerCase() })
            }
          />
        </label>
      </div>
      <label>
        Lyrics (optional)
        <textarea
          rows={6}
          maxLength={100000}
          value={value.lyrics}
          placeholder="Paste original-language lyrics or timestamped LRC lyrics"
          onChange={(e) => onChange({ ...value, lyrics: e.target.value })}
        />
      </label>
      <label>
        Import lyrics
        <input
          type="file"
          accept=".txt,.lrc"
          onChange={(e) => void readLyrics(e.target.files?.[0])}
        />
      </label>
      {fileError && (
        <p role="alert" className="job-error">
          {fileError}
        </p>
      )}
      <p>
        We try LRCLIB automatically. Supplied lyrics take priority; Japanese is
        converted to romaji after syncing.
      </p>
    </fieldset>
  );
}

function LyricCorrection({
  job,
  save,
}: {
  job: Job;
  save: (settings: LyricSettings) => Promise<void>;
}) {
  const [value, setValue] = useState<LyricSettings>({
    ...emptyLyrics,
    ...job.lyric_settings,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  return (
    <details className="lyric-options">
      <summary>Correct lyrics and rebuild</summary>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setSaving(true);
          setError("");
          try {
            await save(value);
          } catch (err) {
            setError(err instanceof Error ? err.message : "Rebuild failed.");
          } finally {
            setSaving(false);
          }
        }}
      >
        <LyricFields value={value} onChange={setValue} disabled={saving} />
        <p>
          Prepared audio and melody analysis are reused. The previous export
          stays on disk until the new package is ready.
        </p>
        {error && (
          <p className="job-error" role="alert">
            {error}
          </p>
        )}
        <button className="create-button" disabled={saving}>
          {saving ? "Queueing…" : "Rebuild with corrections"}
        </button>
      </form>
    </details>
  );
}

function Elapsed({ job }: { job: Job }) {
  const [now, setNow] = useState(Date.now() / 1000);
  useEffect(() => {
    if (job.status !== "running") return;
    const tick = () => {
      if (!document.hidden) setNow(Date.now() / 1000);
    };
    const timer = window.setInterval(tick, 1000);
    document.addEventListener("visibilitychange", tick);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [job.status]);
  return (
    <span>
      {formatElapsed(
        (job.elapsed_seconds || 0) +
          (job.started_at ? Math.max(0, now - job.started_at) : 0),
      )}
    </span>
  );
}

type Api = (path: string, body?: object) => Promise<any>;
class ApiError extends Error {
  constructor(
    message: string,
    public code?: string,
  ) {
    super(message);
  }
}

const JobCard = React.memo(function JobCard({
  job,
  position,
  post,
  update,
  chooseFolder,
  hasFolder,
  folderBusy,
}: {
  job: Job;
  position?: number;
  post: Api;
  update: (job: Job) => void;
  chooseFolder: () => Promise<boolean>;
  hasFolder: boolean;
  folderBusy: boolean;
}) {
  const [pending, setPending] = useState("");
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [cleanupBytes, setCleanupBytes] = useState<number | null>(null);
  const [notice, setNotice] = useState("");
  const active = ["running", "queued"].includes(job.status);
  const cleaned = job.cleaned_at != null;
  const available = !cleaned && job.local_available !== false;
  async function action(name: string, body?: object) {
    setPending(name);
    setError("");
    setNotice("");
    try {
      if (name === "export" && !hasFolder && !(await chooseFolder())) return;
      const result = await post(`/api/jobs/${job.id}/${name}`, body);
      if (result.id) update(result);
      if (name === "export") {
        setConflict(false);
        setNotice("Added to your karaoke Songs folder.");
      }
      if (name === "cleanup") setCleanupBytes(null);
    } catch (e) {
      if (e instanceof ApiError && e.code === "destination_exists")
        setConflict(true);
      else setError(e instanceof Error ? e.message : "Please try again.");
    } finally {
      setPending("");
    }
  }
  async function previewCleanup() {
    setPending("cleanup-preview");
    setError("");
    try {
      const response = await fetch(`/api/jobs/${job.id}/cleanup`);
      const data = await response.json();
      if (!response.ok)
        throw new Error(data.detail || "Could not calculate disk usage.");
      setCleanupBytes(data.bytes);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Please try again.");
    } finally {
      setPending("");
    }
  }
  return (
    <article
      className={`song-card ${active ? "active-job" : ""}`}
      aria-label={job.title}
    >
      <div className={`song-icon ${job.status}`}>
        <Music2 size={22} />
      </div>
      <div className="song-body">
        <div className="song-heading">
          <h3>{job.title}</h3>
          <span className={`status ${job.status}`}>
            {job.status === "running" ? (
              <LoaderCircle size={12} className="spin" />
            ) : job.status === "completed" ? (
              <Check size={12} />
            ) : (
              <Clock3 size={12} />
            )}
            {cleaned
              ? "Cleaned up"
              : job.status === "completed"
                ? "Ready"
                : job.status === "running"
                  ? "Creating"
                  : job.status === "queued"
                    ? "Queued"
                    : job.status === "failed"
                      ? "Needs attention"
                      : "Cancelled"}
          </span>
        </div>
        <p className="song-meta">
          {job.processing_mode === "fast" ? "Fast" : "Quality"} ·{" "}
          {job.source_type === "youtube" ? "YouTube" : "MP4"}
          {job.elapsed_seconds != null && job.status !== "queued" && (
            <>
              {" "}
              · <Elapsed job={job} />
            </>
          )}
        </p>
        {job.status === "running" && (
          <div className="job-progress">
            <div
              className="progress-track"
              role="progressbar"
              aria-label={`${job.title} progress`}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(job.progress * 100)}
            >
              <span style={{ width: `${Math.max(3, job.progress * 100)}%` }} />
            </div>
            <p>
              {job.cancel_requested ? "Stopping safely…" : labels[job.stage]}{" "}
              <span>
                {stages.indexOf(job.stage) + 1} of {stages.length}
              </span>
            </p>
            {job.activity && !job.cancel_requested && (
              <p className="stage-activity">{job.activity}</p>
            )}
          </div>
        )}
        {job.status === "queued" && (
          <p className="queued-note">
            Queue position {position}. Your Mac processes one song at a time.
          </p>
        )}
        {job.error && <p className="job-error">{job.error}</p>}
        {job.warnings.length > 0 && (
          <details className="quality">
            <summary>
              <AlertTriangle size={14} /> {job.warnings.length} quality{" "}
              {job.warnings.length === 1 ? "notice" : "notices"}
            </summary>
            <ul>
              {job.warnings.map((warning, i) => (
                <li key={i}>{warning}</li>
              ))}
            </ul>
          </details>
        )}
        {job.export_receipt?.path && (
          <p className="export-path">
            Last added to: <span>{job.export_receipt.path}</span>
          </p>
        )}
        {cleaned && (
          <p className="song-meta">
            Local working files removed. Any copy in your karaoke folder is
            kept.
          </p>
        )}
        {notice && (
          <p role="status" className="success-note">
            {notice}
          </p>
        )}
        {error && (
          <p role="alert" className="job-error">
            {error}
          </p>
        )}
        {conflict && (
          <div
            className="inline-choice"
            role="group"
            aria-label="Existing song"
          >
            <p>
              A song with this name already exists. Keep both creates a separate
              copy.
            </p>
            <button
              className="create-button"
              disabled={!!pending}
              onClick={() => void action("export", { collision: "keep_both" })}
            >
              Keep both
            </button>
            <button
              disabled={!!pending}
              onClick={() => {
                if (
                  window.confirm(
                    "Replace the existing song folder with this version? Its current contents will be replaced.",
                  )
                )
                  void action("export", { collision: "replace" });
              }}
            >
              Replace existing
            </button>
            <button disabled={!!pending} onClick={() => setConflict(false)}>
              Cancel
            </button>
          </div>
        )}
        {cleanupBytes !== null && (
          <div
            className="inline-choice"
            role="group"
            aria-label="Confirm cleanup"
          >
            <p>
              Free {formatBytes(cleanupBytes)}. This removes local audio,
              exports, and rebuild files. You will need the source again to make
              corrections. Any copies saved elsewhere and export history are kept.
              {!job.export_receipt?.path && " No direct folder export is recorded for this job. Keep a ZIP or add it to karaoke before cleanup if you want to keep the song."}
            </p>
            <button disabled={!!pending} onClick={() => void action("cleanup")}>
              Clean up local files
            </button>
            <button disabled={!!pending} onClick={() => setCleanupBytes(null)}>
              Keep files
            </button>
          </div>
        )}
        <div className="job-buttons">
          {job.status === "completed" && available && (
            <button
              className="create-button"
              disabled={!!pending || folderBusy}
              onClick={() => void action("export", {})}
            >
              <FolderOpen size={16} />{" "}
              {pending === "export" ? "Adding…" : "Add to karaoke"}
            </button>
          )}
          {active && (
            <button
              disabled={!!pending || job.cancel_requested}
              onClick={() => void action("cancel")}
            >
              <X size={15} /> Cancel
            </button>
          )}
          {!active && !cleaned && job.status !== "completed" && (
            <button disabled={!!pending} onClick={() => void action("retry")}>
              <RotateCcw size={15} /> Retry
            </button>
          )}
        </div>
        {!active && !cleaned && (
          <details className="job-options">
            <summary>More options</summary>
            <div className="secondary-actions">
              {job.status === "completed" && available && (
                <>
                  <a href={`/api/jobs/${job.id}/download`}>
                    <ArrowDownToLine size={15} /> Download ZIP
                  </a>
                  <button
                    disabled={!!pending}
                    onClick={() => void action("open-folder")}
                  >
                    <FolderOpen size={15} /> Open local folder
                  </button>
                  <a
                    href={`/api/jobs/${job.id}/report`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Diagnostics
                  </a>
                </>
              )}
              <button
                disabled={!!pending}
                onClick={() => void previewCleanup()}
              >
                <Trash2 size={15} /> Clean up…
              </button>
            </div>
            <LyricCorrection
              job={job}
              save={async (settings) => {
                const updated = await post(
                  `/api/jobs/${job.id}/rebuild`,
                  settings,
                );
                update(updated);
              }}
            />
            <p className="mode-rebuild">
              <button
                disabled={!!pending}
                onClick={() =>
                  void action("processing-mode", {
                    processing_mode:
                      job.processing_mode === "fast" ? "quality" : "fast",
                  })
                }
              >
                Rebuild in {job.processing_mode === "fast" ? "Quality" : "Fast"}{" "}
                mode
              </button>{" "}
              Prepared audio and pitch are reused.
            </p>
          </details>
        )}
      </div>
    </article>
  );
});

function App() {
  const [page, setPage] = useState<"studio" | "benchmarks" | "about">("studio");
  const [shutdown, setShutdown] = useState<"running" | "stopping" | "stopped">(
    "running",
  );
  const [health, setHealth] = useState<Health | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [songsFolder, setSongsFolder] = useState<string | null>(null);
  const [choosing, setChoosing] = useState(false);
  const [mode, setMode] = useState<"youtube" | "file">("youtube");
  const [processingMode, setProcessingMode] = useState<"quality" | "fast">(
    "quality",
  );
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [error, setError] = useState("");
  const [lyricSettings, setLyricSettings] = useState<LyricSettings>({
    ...emptyLyrics,
  });
  const [connection, setConnection] = useState("");
  const [help, setHelp] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const refreshNow = useRef<() => void>(() => {});
  const folderPickerBusy = useRef(false);
  const mutationVersion = useRef(0);
  const hasOlder = useRef(false);
  const requestVersion = useRef(0);

  useEffect(() => {
    if (shutdown !== "running") return;
    let disposed = false,
      fetching = false,
      rerun = false;
    let timer: number | undefined;
    let controller: AbortController | undefined;
    const refresh = async () => {
      clearTimeout(timer);
      if (disposed || document.hidden) return;
      if (fetching) {
        rerun = true;
        return;
      }
      fetching = true;
      const version = mutationVersion.current;
      const request = ++requestVersion.current;
      controller = new AbortController();
      const timeout = window.setTimeout(() => controller?.abort(), 10000);
      let active = false;
      try {
        const responses = await Promise.all(
          ["/api/health", "/api/jobs/feed?limit=20", "/api/settings"].map(
            (path) => fetch(path, { signal: controller!.signal }),
          ),
        );
        if (responses.some((response) => !response.ok))
          throw new Error("Connection unavailable");
        const [h, feed, settings] = await Promise.all(
          responses.map((response) => response.json()),
        );
        if (disposed) return;
        setHealth(h);
        setSongsFolder(settings.songs_folder);
        if (h.shutting_down) setShutdown("stopping");
        active = feed.active.length > 0;
        if (
          version === mutationVersion.current &&
          request === requestVersion.current
        ) {
          const incoming: Job[] = [...feed.active, ...feed.recent];
          setJobs((current) => {
            const previous = new Map(current.map((job) => [job.id, job]));
            const stable = incoming.map((job) => {
              const old = previous.get(job.id);
              return old && JSON.stringify(old) === JSON.stringify(job)
                ? old
                : job;
            });
            const ids = new Set(incoming.map((job) => job.id));
            // Preserve explicitly loaded older pages. Remove stale active snapshots.
            const older = hasOlder.current
              ? current.filter(
                  (job) =>
                    !ids.has(job.id) &&
                    !["running", "queued"].includes(job.status),
                )
              : [];
            const result = [...stable, ...older];
            return result.length === current.length &&
              result.every((job, i) => job === current[i])
              ? current
              : result;
          });
          if (!hasOlder.current) setNext(feed.next);
        }
        setConnection("");
      } catch {
        if (!disposed)
          setConnection(
            "Cannot reach the local app. Keep Start.command running; your songs are saved.",
          );
      } finally {
        clearTimeout(timeout);
        fetching = false;
        if (!disposed && !document.hidden) {
          const delay = rerun ? 0 : active ? 2000 : 15000;
          rerun = false;
          timer = window.setTimeout(() => void refresh(), delay);
        }
      }
    };
    const visibility = () => {
      clearTimeout(timer);
      if (!document.hidden) void refresh();
    };
    refreshNow.current = () => void refresh();
    document.addEventListener("visibilitychange", visibility);
    void refresh();
    return () => {
      disposed = true;
      controller?.abort();
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", visibility);
      refreshNow.current = () => {};
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
    return () => {
      disposed = true;
      clearInterval(timer);
    };
  }, [shutdown]);

  const post = useCallback(
    async (path: string, body?: object) => {
      mutationVersion.current += 1;
      const response = await fetch(path, {
        method: "POST",
        headers: {
          "X-Karapincho-Token": health?.token || "",
          ...(body ? { "Content-Type": "application/json" } : {}),
        },
        body: body ? JSON.stringify(body) : undefined,
      });
      const data = await response.json();
      mutationVersion.current += 1;
      if (!response.ok)
        throw new ApiError(
          typeof data.detail === "string"
            ? data.detail
            : data.detail?.message || "Please check your input and try again.",
          data.detail?.code,
        );
      return data;
    },
    [health?.token],
  );
  const update = useCallback((job: Job) => {
    mutationVersion.current += 1;
    setJobs((current) => [
      job,
      ...current.filter((item) => item.id !== job.id),
    ]);
    refreshNow.current();
  }, []);
  const chooseFolder = useCallback(async () => {
    if (folderPickerBusy.current) return false;
    folderPickerBusy.current = true;
    setChoosing(true);
    try {
      const settings = await post("/api/settings/choose-folder");
      setSongsFolder(settings.songs_folder);
      return !settings.cancelled;
    } finally {
      folderPickerBusy.current = false;
      setChoosing(false);
    }
  }, [post]);
  function chooseFile(selected?: File) {
    if (!selected || busy) return;
    setError("");
    if (!selected.name.toLowerCase().endsWith(".mp4"))
      return setError("Choose an MP4 video with an audio track.");
    if (selected.size > (health?.max_bytes || 2 * 1024 ** 3))
      return setError(
        "This video is larger than 2 GB. Please use a smaller MP4.",
      );
    setFile(selected);
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
            : reject(
                new Error(
                  typeof data.detail === "string"
                    ? data.detail
                    : "Upload failed.",
                ),
              );
        } catch {
          reject(new Error("Upload failed. Check that the app is running."));
        }
      };
      const form = new FormData();
      form.append("file", selected);
      form.append("lyric_settings", JSON.stringify(lyricSettings));
      form.append("processing_mode", processingMode);
      xhr.send(form);
    });
  }
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    setUploadProgress(0);
    mutationVersion.current += 1;
    try {
      const job =
        mode === "youtube"
          ? await post("/api/jobs/url", {
              url: url.trim(),
              lyric_settings: lyricSettings,
              processing_mode: processingMode,
            })
          : await uploadFile(file!);
      update(job);
      setUrl("");
      setFile(null);
      setLyricSettings({ ...emptyLyrics });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create song.");
    } finally {
      setBusy(false);
    }
  }
  async function loadMore() {
    if (!next) return;
    setLoadingMore(true);
    try {
      const response = await fetch(
        `/api/jobs/feed?limit=20&before=${encodeURIComponent(next)}`,
      );
      if (!response.ok) throw new Error("Could not load recent jobs.");
      const feed = await response.json();
      hasOlder.current = true;
      setJobs((current) => {
        const ids = new Set(current.map((job) => job.id));
        return [
          ...current,
          ...feed.recent.filter((job: Job) => !ids.has(job.id)),
        ];
      });
      setNext(feed.next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load recent jobs.");
    } finally {
      setLoadingMore(false);
    }
  }
  async function quitApp() {
    if (
      !window.confirm(
        "Quit Karapincho? Any song in progress will resume from its last completed stage when you reopen the app.",
      )
    )
      return;
    setShutdown("stopping");
    try {
      await post("/api/shutdown");
    } catch (e) {
      setShutdown("running");
      setError(e instanceof Error ? e.message : "Could not shut down.");
    }
  }
  const active = jobs
    .filter((job) => ["running", "queued"].includes(job.status))
    .sort((a, b) =>
      a.status === "running"
        ? -1
        : b.status === "running"
          ? 1
          : a.created - b.created,
    );
  const recent = jobs
    .filter((job) => !["running", "queued"].includes(job.status))
    .sort((a, b) => b.created - a.created);
  if (shutdown !== "running")
    return (
      <div className="shutdown-screen" role="status">
        <Power size={36} />
        <h1>
          {shutdown === "stopped"
            ? "Karapincho is stopped."
            : "Karapincho is shutting down…"}
        </h1>
        <p>
          Your songs are saved. Unfinished songs resume from their last
          completed stage.
        </p>
        <p>
          Open <strong>Start.command</strong> to run Karapincho again.
        </p>
      </div>
    );

  return (
    <div className="app-shell workflow-shell">
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="Karapincho home">
          <span className="brand-icon">
            <Capybara />
          </span>
          karapincho<span className="brand-dot">.</span>
        </a>
        <div className="workspace-label">YOUR STUDIO</div>
        <button
          className={`nav-item ${page === "studio" ? "selected" : ""}`}
          aria-label="Song studio"
          onClick={() => setPage("studio")}
        >
          <AudioLines size={19} /> Song studio
        </button>
        <div className="secondary-nav" aria-label="Studio information">
          <button
            className={`nav-item ${page === "benchmarks" ? "selected" : ""}`}
            aria-label="Benchmarks"
            onClick={() => setPage("benchmarks")}
          >
            <Clock3 size={18} /> Benchmarks
          </button>
          <button
            className={`nav-item ${page === "about" ? "selected" : ""}`}
            aria-label="About"
            onClick={() => setPage("about")}
          >
            <Info size={18} /> About
          </button>
        </div>
        <div className="sidebar-bottom">
          <div>
            <span className="live-dot" /> Runs on your Mac
          </div>
          <p>Local inference · no telemetry.</p>
          <button
            onClick={() => {
              setPage("studio");
              setHelp(!help);
            }}
          >
            <CircleHelp size={16} /> How it works
          </button>
        </div>
      </aside>
      <main>
        <header className="topbar">
          <span>
            {page === "studio"
              ? "Song studio"
              : page === "benchmarks"
                ? "Benchmarks"
                : "About"}
          </span>
          <div className="topbar-actions">
            <div className="local-badge">
              <HardDrive size={14} /> LOCAL STUDIO
            </div>
            <button
              className="quit-button"
              disabled={!health || busy}
              onClick={() => void quitApp()}
            >
              <Power size={16} /> Quit Karapincho
            </button>
          </div>
        </header>
        <div className="content">
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
          {page === "benchmarks" ? (
            <Benchmark post={post} />
          ) : page === "about" ? (
            <About version={health?.version} />
          ) : (
            <>
              <div
                className={`page-heading ${jobs.length ? "compact-heading" : ""}`}
              >
                <div>
                  <p className="eyebrow">CREATE → PROCESS → ADD TO KARAOKE</p>
                  <h1>
                    {jobs.length
                      ? "Bring your next song."
                      : "Your next karaoke night starts here."}
                  </h1>
                  {!jobs.length && (
                    <p className="subtitle">
                      A video in. A song ready for your karaoke folder.
                    </p>
                  )}
                </div>
                {!jobs.length && (
                  <div className="heading-art" aria-hidden="true">
                    <div className="disc">
                      <div className="disc-inner">
                        <Mic2 size={30} />
                      </div>
                    </div>
                  </div>
                )}
              </div>
              {health && !health.ready && (
                <div className="alert" role="status">
                  <AlertTriangle size={18} />
                  <span>
                    Setup is incomplete: {health.missing.join(", ")}. Run
                    Setup.command, then restart the app.
                  </span>
                </div>
              )}
              {help && (
                <div className="help-panel">
                  <button
                    className="close-help"
                    aria-label="Close help"
                    onClick={() => setHelp(false)}
                  >
                    <X size={18} />
                  </button>
                  <h3>From video to karaoke folder.</h3>
                  <p>
                    Paste one public YouTube link or upload an MP4. Karapincho
                    isolates vocals for analysis, syncs lyrics and melody, and
                    builds an UltraStar package with the original vocals.
                  </p>
                  <p>
                    Choose your karaoke Songs folder once. When a song finishes,
                    check its quality notices and select Add to karaoke. ZIP
                    downloads remain available under More options.
                  </p>
                  <p>
                    Quality uses the established transcription model. Fast uses
                    a smaller model and may miss lines or mishear lyrics. Processing may
                    take longer than the song itself.
                  </p>
                </div>
              )}
              <section className="creator-card">
                <div className="card-heading">
                  <span className="orange-icon">
                    <Plus size={20} />
                  </span>
                  <div>
                    <h2>Create a song</h2>
                    <p>One video. Ready for your next singalong.</p>
                  </div>
                </div>
                <form onSubmit={submit}>
                  <div
                    className="source-tabs"
                    role="tablist"
                    aria-label="Song source"
                  >
                    {(["youtube", "file"] as const).map((source, i) => (
                      <button
                        key={source}
                        type="button"
                        role="tab"
                        id={`source-${source}`}
                        aria-controls="source-panel"
                        aria-selected={mode === source}
                        tabIndex={mode === source ? 0 : -1}
                        disabled={busy}
                        className={mode === source ? "active" : ""}
                        onClick={() => setMode(source)}
                        onKeyDown={(e) => {
                          if (
                            ["ArrowLeft", "ArrowRight", "Home", "End"].includes(
                              e.key,
                            )
                          ) {
                            e.preventDefault();
                            const value =
                              e.key === "Home"
                                ? "youtube"
                                : e.key === "End"
                                  ? "file"
                                  : i === 0
                                    ? "file"
                                    : "youtube";
                            setMode(value);
                            document.getElementById(`source-${value}`)?.focus();
                          }
                        }}
                      >
                        {source === "youtube" ? (
                          <>
                            <Link2 size={16} /> YouTube link
                          </>
                        ) : (
                          <>
                            <FileVideo size={16} /> Upload video
                          </>
                        )}
                      </button>
                    ))}
                  </div>
                  <div
                    id="source-panel"
                    role="tabpanel"
                    aria-labelledby={`source-${mode}`}
                  >
                    {mode === "youtube" ? (
                      <div className="url-area">
                        <label htmlFor="youtube-url">YOUTUBE VIDEO URL</label>
                        <div className="url-input">
                          <Link2 size={20} />
                          <input
                            id="youtube-url"
                            type="url"
                            placeholder="https://www.youtube.com/watch?v=…"
                            value={url}
                            onChange={(e) => setUrl(e.target.value)}
                            required
                            disabled={busy}
                            autoComplete="off"
                          />
                        </div>
                        <p className="input-hint">
                          Download blocked?{" "}
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
                          disabled={busy}
                          className={`dropzone ${dragging ? "dragging" : ""}`}
                          onClick={() => input.current?.click()}
                          onDragOver={(e) => {
                            e.preventDefault();
                            setDragging(true);
                          }}
                          onDragLeave={() => setDragging(false)}
                          onDrop={(e) => {
                            e.preventDefault();
                            setDragging(false);
                            chooseFile(e.dataTransfer.files[0]);
                          }}
                        >
                          <Upload size={24} />
                          <strong>
                            {file ? file.name : "Drop your video here"}
                          </strong>
                          <span>
                            {file
                              ? `${formatBytes(file.size)} · Click to choose another`
                              : "or click to browse · MP4 · Up to 2 GB / 20 minutes"}
                          </span>
                        </button>
                      </div>
                    )}
                  </div>
                  <fieldset className="processing-options" disabled={busy}>
                    <legend>Processing mode</legend>
                    <label
                      className={processingMode === "quality" ? "selected" : ""}
                    >
                      <input
                        type="radio"
                        name="processing-mode"
                        value="quality"
                        checked={processingMode === "quality"}
                        onChange={() => setProcessingMode("quality")}
                      />
                      <span>
                        <strong>Quality</strong>
                        <small>Recommended · established accuracy</small>
                      </span>
                    </label>
                    <label
                      className={processingMode === "fast" ? "selected" : ""}
                    >
                      <input
                        type="radio"
                        name="processing-mode"
                        value="fast"
                        checked={processingMode === "fast"}
                        onChange={() => setProcessingMode("fast")}
                      />
                      <span>
                        <strong>Fast</strong>
                        <small>
                          Smaller model · may miss lines or mishear lyrics
                        </small>
                      </span>
                    </label>
                  </fieldset>
                  <details className="lyric-options">
                    <summary>Song details and lyrics (optional)</summary>
                    <LyricFields
                      value={lyricSettings}
                      onChange={setLyricSettings}
                      disabled={busy}
                    />
                  </details>
                  <div className="create-row">
                    <p>Local processing · original vocals kept</p>
                    <button
                      className="create-button"
                      disabled={
                        busy ||
                        !health?.ready ||
                        !!connection ||
                        (mode === "youtube" ? !url.trim() : !file)
                      }
                    >
                      {busy ? (
                        <LoaderCircle size={18} className="spin" />
                      ) : (
                        <Sparkles size={18} />
                      )}
                      {busy
                        ? mode === "file"
                          ? `Uploading ${uploadProgress}%`
                          : "Adding song…"
                        : "Create song"}
                      <ArrowRight size={17} />
                    </button>
                  </div>
                </form>
              </section>
              {active.length > 0 && (
                <section
                  className="queue-section"
                  aria-labelledby="queue-title"
                >
                  <div className="section-heading">
                    <h2 id="queue-title">
                      In progress <span>{active.length}</span>
                    </h2>
                    <p>One song at a time, with safe restart.</p>
                  </div>
                  <div className="song-list">
                    {active.map((job) => (
                      <JobCard
                        key={job.id}
                        job={job}
                        position={
                          active
                            .filter((item) => item.status === "queued")
                            .findIndex((item) => item.id === job.id) + 1
                        }
                        post={post}
                        update={update}
                        chooseFolder={chooseFolder}
                        hasFolder={!!songsFolder}
                        folderBusy={choosing}
                      />
                    ))}
                  </div>
                </section>
              )}
              <section
                className="destination-card"
                aria-label="Karaoke destination"
              >
                <FolderOpen size={21} />
                <div>
                  <h2>Your karaoke Songs folder</h2>
                  <p>
                    {songsFolder ||
                      "Choose once, then add each finished song with one click."}
                  </p>
                </div>
                <button
                  disabled={choosing || !health}
                  onClick={() =>
                    void chooseFolder().catch((e) => setError(e.message))
                  }
                >
                  {choosing
                    ? "Choosing…"
                    : songsFolder
                      ? "Change folder"
                      : "Choose folder"}
                </button>
              </section>
              <section
                className="recent-section"
                aria-labelledby="recent-title"
              >
                <div className="section-heading">
                  <h2 id="recent-title">Recent jobs</h2>
                  <p>
                    Check results, add to karaoke, or recover a previous
                    attempt.
                  </p>
                </div>
                {recent.length ? (
                  <div className="song-list">
                    {recent.map((job) => (
                      <JobCard
                        key={job.id}
                        job={job}
                        post={post}
                        update={update}
                        chooseFolder={chooseFolder}
                        hasFolder={!!songsFolder}
                        folderBusy={choosing}
                      />
                    ))}
                  </div>
                ) : (
                  <div className="recent-empty">
                    <Disc3 size={24} />
                    <p>
                      {active.length
                        ? "Finished songs will appear here."
                        : "Your first song starts with a link or a video above."}
                    </p>
                  </div>
                )}
                {next && (
                  <button
                    className="load-more"
                    disabled={loadingMore}
                    onClick={() => void loadMore()}
                  >
                    {loadingMore ? "Loading…" : "Load older jobs"}
                  </button>
                )}
              </section>
            </>
          )}
          <footer className="page-footer">
            <span>Made for the songs you can’t help singing.</span>
            <span>
              Local AI{health?.version ? ` · v${health.version}` : ""}
            </span>
          </footer>
        </div>
      </main>
    </div>
  );
}

function formatBytes(bytes: number) {
  return bytes >= 1024 ** 3
    ? `${(bytes / 1024 ** 3).toFixed(1)} GB`
    : `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

function formatElapsed(seconds: number) {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainder = total % 60;
  return hours
    ? `${hours}h ${minutes}m ${remainder}s`
    : `${minutes}m ${remainder}s`;
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
