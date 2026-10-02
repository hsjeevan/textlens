import type { Run, RunStatus } from "../types";

const RUN_STEPS: [string, string][] = [
  ["Uploaded", "file received"],
  ["Queued", "waiting for a worker"],
  ["Analysing", "tokens → keywords · tone · themes"],
  ["Ready", "building dashboard"],
];

interface PipelineProps {
  filename: string;
  status: RunStatus;
  elapsed: number;
  runId: string;
}

/** Live progress card shown while a run is pending or running. */
export function Pipeline({ filename, status, elapsed, runId }: PipelineProps) {
  // Index of the step currently in progress; earlier steps are done.
  const active = ({ pending: 1, running: 2 } as Partial<Record<RunStatus, number>>)[status] ?? 3;
  return (
    <div className="pipeline">
      <div className="pipeline-top">
        <div>
          <div className="mono">Now processing</div>
          <div className="file">{filename}</div>
        </div>
        <div className="pill"><span className="dot good" />{elapsed.toFixed(1)}s · {status}</div>
      </div>
      <div className="steps">
        {RUN_STEPS.map(([name, sub], i) => (
          <div key={name} className={`step ${i < active ? "done" : i === active ? "active" : ""}`}>
            <div className="bar" />
            <div className="name">{name}</div>
            <div className="sub">{sub}</div>
          </div>
        ))}
      </div>
      <div className="footnote mono">run {runId}</div>
    </div>
  );
}

const STEP_LABELS: Record<string, string> = {
  tokens: "Tokenize",
  stats: "Counts",
  keywords: "Keywords",
  tone: "Tone",
  themes: "Themes",
};

/** Banner saying whether this result came from the Redis cache or the NLP pipeline. */
export function CacheSource({ run }: { run: Run }) {
  // Runs recorded before per-step tracking existed have no `cache` field.
  const cache = run.cache ?? { result: run.cache_hit ? "cache" : "nlp", steps: {}, forced: false };
  const steps = cache.steps ?? {};

  let dot: string, headline: string, detail: string;
  if (cache.forced) {
    [dot, headline] = ["forced", "Recomputed · cache skipped"];
    detail = "Every step was re-run by the NLP pipeline and the cache was refreshed.";
  } else if (cache.result === "cache") {
    [dot, headline] = ["cache", "Served from Redis cache"];
    detail = "This exact text was analysed before; the stored result was returned instantly.";
  } else if (Object.values(steps).includes("cache")) {
    [dot, headline] = ["good", "Computed · partly cached"];
    detail = "Some steps were reused from the cache; the rest ran through the NLP pipeline.";
  } else {
    [dot, headline] = ["good", "Computed by NLP pipeline"];
    detail = "Nothing was cached for this text, so every step ran fresh.";
  }

  const entries = Object.entries(steps);
  return (
    <div className="pipeline source">
      <div className="pipeline-top">
        <div>
          <div className="mono">Result source</div>
          <div className="footnote" style={{ marginTop: 6 }}>{detail}</div>
        </div>
        <div className="pill big"><span className={`dot ${dot}`} />{headline}</div>
      </div>
      {entries.length > 0 && (
        <div className="steps">
          {entries.map(([step, src]) => (
            <div key={step} className={`step ${src}`}>
              <div className="bar" />
              <div className="name">{STEP_LABELS[step] ?? step}</div>
              <div className="sub">{src === "cache" ? "Redis cache" : "NLP pipeline"}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
