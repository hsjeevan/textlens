import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import { ApiError, apiOnline, clearCache, fetchInsights, uploadFile } from "./api";
import { Colophon, Hero, Nav, Notice, Toast } from "./components/Chrome";
import { Dashboard } from "./components/Dashboard";
import { Pipeline } from "./components/Pipeline";
import type { Run } from "./types";

const POLL_INTERVAL_MS = 1000;
const POLL_TIMEOUT_SECONDS = 120;
const HEALTH_INTERVAL_MS = 5000;
const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;
// Consecutive failed polls tolerated before giving up (e.g. a brief API blip).
const MAX_POLL_ERRORS = 5;

type Phase =
  | { kind: "idle" }
  | { kind: "polling"; runId: string; filename: string; started: number; run: Pick<Run, "status"> }
  | { kind: "done"; run: Run; elapsed: number }
  | { kind: "error"; title: string; body: string };

const IDLE: Phase = { kind: "idle" };

function useApiOnline(): boolean | null {
  const [online, setOnline] = useState<boolean | null>(null);
  useEffect(() => {
    let alive = true;
    const check = () => apiOnline().then((ok) => alive && setOnline(ok));
    check();
    const id = setInterval(check, HEALTH_INTERVAL_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);
  return online;
}

function useToast() {
  const [toast, setToast] = useState<{ message: string; kind: "info" | "error" } | null>(null);
  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(id);
  }, [toast]);
  return [toast, setToast] as const;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function App() {
  const online = useApiOnline();
  const [phase, setPhase] = useState<Phase>(IDLE);
  const [file, setFile] = useState<File | null>(null);
  const [force, setForce] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [now, setNow] = useState(() => performance.now());
  const [toast, setToast] = useToast();
  const inputRef = useRef<HTMLInputElement>(null);

  const busy = phase.kind === "polling";

  // Poll the run every second until it completes, fails or times out.
  const pollingRunId = phase.kind === "polling" ? phase.runId : null;
  useEffect(() => {
    if (!pollingRunId) return;
    let cancelled = false;
    let errors = 0;
    let timer: ReturnType<typeof setTimeout>;

    const tick = async () => {
      let run: Run | null = null;
      try {
        run = await fetchInsights(pollingRunId);
        errors = 0;
      } catch (exc) {
        errors += 1;
        if (errors >= MAX_POLL_ERRORS && !cancelled) {
          setPhase({ kind: "error", title: "Lost contact with the API", body: String((exc as Error).message) });
          return;
        }
      }
      if (cancelled) return;

      setNow(performance.now());
      setPhase((prev) => {
        if (prev.kind !== "polling" || prev.runId !== pollingRunId) return prev;
        const elapsed = (performance.now() - prev.started) / 1000;
        const current = run ?? prev.run;
        if (current.status === "completed" && run?.result) {
          return { kind: "done", run, elapsed };
        }
        if (current.status === "failed") {
          return { kind: "error", title: "Analysis failed", body: run?.error || "Unknown error" };
        }
        if (elapsed > POLL_TIMEOUT_SECONDS) {
          return {
            kind: "error",
            title: "Still running",
            body: `No result after ${POLL_TIMEOUT_SECONDS}s. Run ID: ${pollingRunId}`,
          };
        }
        return { ...prev, run: current };
      });
      timer = setTimeout(tick, POLL_INTERVAL_MS);
    };

    tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [pollingRunId]);

  const chooseFile = useCallback((picked: File | null | undefined) => {
    if (!picked) return;
    if (!picked.name.toLowerCase().endsWith(".txt")) {
      setPhase({ kind: "error", title: "Unsupported file", body: "Only .txt files are supported." });
      return;
    }
    setFile(picked);
  }, []);

  const submit = async () => {
    if (!file) return;
    if (file.size > MAX_UPLOAD_BYTES) {
      setPhase({ kind: "error", title: "File too large", body: "The limit is 5 MB." });
      return;
    }
    try {
      const resp = await uploadFile(file, force);
      const started = performance.now();
      setNow(started);
      setPhase({ kind: "polling", runId: resp.run_id, filename: file.name, started, run: { status: resp.status } });
    } catch (exc) {
      setPhase({ kind: "error", title: "Upload rejected", body: exc instanceof ApiError ? exc.message : String(exc) });
    }
  };

  const reset = () => {
    setPhase(IDLE);
    setFile(null);
    if (inputRef.current) inputRef.current.value = "";
  };

  const onClearCache = async () => {
    try {
      const n = await clearCache();
      setToast({ message: `Cleared ${n} cached entr${n === 1 ? "y" : "ies"}`, kind: "info" });
    } catch (exc) {
      setToast({ message: `Couldn't clear the cache: ${(exc as Error).message}`, kind: "error" });
    }
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (!busy) chooseFile(e.dataTransfer.files[0]);
  };

  return (
    <main className="page lx">
      <Nav online={online} />
      <Hero />

      <div className="upload">
        <div>
          <div className="upload-label"><span className="num mono">01</span><h3>Start with a file</h3></div>
          <p className="lede" style={{ fontSize: 15, maxWidth: "40ch" }}>
            Upload a .txt file and press analyse. Processing runs in the background; this page updates by itself.
          </p>
        </div>

        <div className="upload-controls">
          <div
            className={`dropzone${dragOver ? " over" : ""}${busy ? " disabled" : ""}`}
            role="button"
            tabIndex={busy ? -1 : 0}
            aria-disabled={busy}
            onClick={() => inputRef.current?.click()}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), inputRef.current?.click())}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
          >
            <div className="hint">
              Drag and drop a file here
              <small>Limit 5 MB · TXT</small>
            </div>
            <span className="browse">Browse files</span>
            <input
              ref={inputRef}
              type="file"
              accept=".txt,text/plain"
              hidden
              disabled={busy}
              onChange={(e) => chooseFile(e.target.files?.[0])}
            />
          </div>

          {file && (
            <div className="chosen">
              <span>{file.name} <span className="size">{formatSize(file.size)}</span></span>
              {!busy && <button type="button" aria-label="Remove file" onClick={reset}>✕</button>}
            </div>
          )}

          {phase.kind === "done" ? (
            <div className="row-2">
              <button className="btn primary" disabled={!file} onClick={submit}>Analyse new file</button>
              <button className="btn secondary" onClick={reset}>Clear results</button>
            </div>
          ) : (
            <button className="btn primary" disabled={!file || busy} onClick={submit}>Analyse text  →</button>
          )}

          <div className="row-cache">
            <label
              className={`toggle${busy ? " disabled" : ""}`}
              title="Ignore any cached result for this file and recompute every step."
            >
              <input type="checkbox" checked={force} disabled={busy} onChange={(e) => setForce(e.target.checked)} />
              <span className="track" />
              Skip cache, re-run NLP
            </label>
            <button
              className="btn secondary"
              disabled={busy}
              onClick={onClearCache}
              title="Delete every cached NLP result in Redis."
            >
              Clear cache
            </button>
          </div>
        </div>
      </div>

      {phase.kind === "polling" && (
        <Pipeline
          filename={phase.filename}
          status={phase.run.status}
          elapsed={Math.max(0, (now - phase.started) / 1000)}
          runId={phase.runId}
        />
      )}
      {phase.kind === "error" && <Notice title={phase.title} body={phase.body} />}
      {phase.kind === "done" && <Dashboard run={phase.run} elapsed={phase.elapsed} />}

      {online === false && (
        <Notice
          title="Backend unreachable"
          body="Start the API (or its port-forward), or point the dashboard at it with TEXTLENS_API_URL."
        />
      )}

      <Colophon />
      {toast && <Toast message={toast.message} kind={toast.kind} />}
    </main>
  );
}
