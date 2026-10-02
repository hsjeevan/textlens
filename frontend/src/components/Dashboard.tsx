import { Fragment, type CSSProperties } from "react";
import { buildInsights } from "../insights";
import { pad2, signed, themeName, thousands } from "../format";
import type { AnalysisResult, Keyword, Run, Themes, Tone } from "../types";
import { Section } from "./Chrome";
import { CacheSource } from "./Pipeline";

function Marquee({ keywords }: { keywords: Keyword[] }) {
  const words = keywords.length ? keywords.map((k) => k.word) : ["no", "keywords", "found"];
  // Content is duplicated so the -50% translate loops seamlessly.
  const items = [...words, ...words];
  return (
    <div className="marquee" aria-hidden="true">
      <div className="marquee-track">
        {items.map((w, i) => (
          <Fragment key={i}>
            <span>{w}</span><i>✳</i>
          </Fragment>
        ))}
      </div>
    </div>
  );
}

function StatTiles({ result }: { result: AnalysisResult }) {
  const { word_count: words, sentence_count: sentences, tone } = result;
  const avg = sentences ? words / sentences : 0;
  const pace = avg < 12 ? "Punchy" : avg <= 20 ? "Balanced" : "Dense";
  const toneDot =
    ({ positive: "var(--div-pos)", negative: "var(--div-neg)" } as Record<string, string>)[tone.label] ??
    "#8c8b82";
  return (
    <div className="stats">
      <div className="tile hero-tile">
        <div className="label">Words</div>
        <div><div className="value">{thousands(words)}</div><div className="note">punctuation excluded</div></div>
      </div>
      <div className="tile">
        <div className="label">Sentences</div>
        <div><div className="value">{thousands(sentences)}</div><div className="note">detected by Punkt</div></div>
      </div>
      <div className="tile">
        <div className="label">Words per sentence</div>
        <div><div className="value">{avg.toFixed(1)}</div><div className="note">{pace} rhythm</div></div>
      </div>
      <div className="tile">
        <div className="label">Overall tone</div>
        <div>
          <div className="value tone-value"><span className="dot" style={{ background: toneDot }} />{tone.label}</div>
          <div className="note">compound {signed(tone.scores.compound)}</div>
        </div>
      </div>
    </div>
  );
}

interface BarRowProps {
  rank: number;
  label: string;
  value: number;
  max: number;
  tip: string;
  delayMs: number;
}

function BarRow({ rank, label, value, max, tip, delayMs }: BarRowProps) {
  const fill: CSSProperties = { width: `${((value / max) * 100).toFixed(1)}%`, animationDelay: `${delayMs}ms` };
  return (
    <div className="bar-row" data-tip={tip}>
      <span className="rank">{pad2(rank)}</span>
      <span className="word">{label}</span>
      <span className="track"><span className="fill" style={fill} /><span className="count">{value}</span></span>
    </div>
  );
}

function KeywordPanel({ keywords }: { keywords: Keyword[] }) {
  if (!keywords.length) {
    return <div className="panel"><div className="footnote">No keywords - the text has no content words.</div></div>;
  }
  const top = Math.max(...keywords.map((k) => k.count));
  const total = keywords.reduce((s, k) => s + k.count, 0);
  const allTied = new Set(keywords.map((k) => k.count)).size === 1;
  return (
    <div className="panel">
      <div className="panel-title"><h3>Top keywords by frequency</h3><span className="mono">stopwords removed</span></div>
      <div className="bars">
        {keywords.map((k, idx) => {
          const i = idx + 1;
          const noun = k.count === 1 ? "occurrence" : "occurrences";
          const share = ((k.count / total) * 100).toFixed(0);
          return (
            <BarRow key={k.word} rank={i} label={k.word} value={k.count} max={top} delayMs={i * 45}
              tip={`${k.word} - ${k.count} ${noun} · ${share}% of top keywords`} />
          );
        })}
      </div>
      {allTied && (
        <div className="footnote">
          Every keyword appears equally often, so the order reflects first appearance in the text.
        </div>
      )}
    </div>
  );
}

function TonePanel({ tone }: { tone: Tone }) {
  const s = tone.scores;
  const parts: [key: "neg" | "neu" | "pos", name: string, value: number][] = [
    ["neg", "Negative", s.neg], ["neu", "Neutral", s.neu], ["pos", "Positive", s.pos],
  ];
  const total = parts.reduce((sum, [, , v]) => sum + v, 0) || 1;
  const segs = parts.filter(([, , v]) => v / total > 0);
  const compound = s.compound;
  const pos = ((compound + 1) / 2) * 100;
  const markerColor = compound >= 0.05 ? "var(--div-pos)" : compound <= -0.05 ? "var(--div-neg)" : "#8c8b82";
  const ind = tone.indicators;
  return (
    <div className="panel">
      <div className="panel-title"><h3>Sentiment mix</h3><span className="mono">VADER</span></div>
      <div className="stack">
        {segs.length ? (
          segs.map(([key, name, v]) => {
            const pct = (v / total) * 100;
            return (
              <div key={key} className={`seg ${key}`} style={{ flex: pct }} data-tip={`${name} - ${pct.toFixed(0)}%`}>
                {/* Only label inside a segment when the text comfortably fits. */}
                {pct >= 12 ? `${pct.toFixed(0)}%` : ""}
              </div>
            );
          })
        ) : (
          <div className="seg neu" style={{ flex: 1 }} />
        )}
      </div>
      <div className="legend">
        {parts.map(([key, name, v]) => (
          <span key={key}>
            <i className="sw" style={{ background: `var(--div-${key === "neu" ? "mid" : key})` }} />
            {name} {((v / total) * 100).toFixed(0)}%
          </span>
        ))}
      </div>
      <div className="scale">
        <div className="axis" />
        <div className="zero" />
        <div className="marker" style={{ left: `${pos.toFixed(1)}%`, background: markerColor }}>
          <span className="marker-label">{signed(compound)}</span>
        </div>
        <div className="ticks"><span>−1 negative</span><span>0</span><span>positive +1</span></div>
      </div>
      <div className="indicators">
        <div><span className="mono">Exclaims</span><b>{ind.exclamation_count}</b></div>
        <div><span className="mono">Questions</span><b>{ind.question_count}</b></div>
        <div><span className="mono">Shouting</span><b>{(ind.uppercase_word_ratio * 100).toFixed(1)}%</b></div>
      </div>
    </div>
  );
}

function ThemePanel({ themes }: { themes: Themes }) {
  const entries = Object.entries(themes.scores);
  if (!entries.length) {
    return (
      <div className="panel">
        <div className="panel-title"><h3>Themes</h3></div>
        <div className="footnote">No theme trigger words found in this text.</div>
      </div>
    );
  }
  const top = Math.max(...entries.map(([, n]) => n));
  const ordered = entries.sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  return (
    <div className="panel">
      <div className="panel-title"><h3>Theme signals</h3><span className="mono">trigger words</span></div>
      <div className="dominant">
        <span className="mono">Dominant</span>
        <b>{themes.dominant.map(themeName).join(" & ")}</b>
      </div>
      <div className="bars themes">
        {ordered.map(([theme, n], idx) => {
          const name = themeName(theme);
          return (
            <BarRow key={theme} rank={idx + 1} label={name} value={n} max={top} delayMs={(idx + 1) * 60}
              tip={`${name} - ${n} trigger word${n !== 1 ? "s" : ""}`} />
          );
        })}
      </div>
    </div>
  );
}

function InsightCards({ result }: { result: AnalysisResult }) {
  return (
    <div className="insights">
      {buildInsights(result).map(([title, body], idx) => (
        <div key={title} className="insight">
          <span className="idx">{pad2(idx + 1)}</span>
          <div><h4>{title}</h4><p>{body}</p></div>
        </div>
      ))}
    </div>
  );
}

function RawData({ result }: { result: AnalysisResult }) {
  return (
    <details className="expander">
      <summary>Data table &amp; raw JSON</summary>
      <div className="body">
        <table className="table">
          <thead><tr><th>rank</th><th>keyword</th><th>count</th></tr></thead>
          <tbody>
            {result.top_keywords.map((k, idx) => (
              <tr key={k.word}><td className="num">{idx + 1}</td><td>{k.word}</td><td className="num">{k.count}</td></tr>
            ))}
          </tbody>
        </table>
        <pre className="json">{JSON.stringify(result, null, 2)}</pre>
      </div>
    </details>
  );
}

function MetaFooter({ run, elapsed }: { run: Run; elapsed: number | null }) {
  const cached = run.cache?.forced
    ? "Recomputed (cache skipped)"
    : run.cache_hit ? "Redis cache hit" : "Fresh analysis";
  const took = elapsed !== null ? `${elapsed.toFixed(1)}s · ${cached}` : cached;
  return (
    <div className="meta">
      <div><span className="mono">File</span><b>{run.filename || "-"}</b></div>
      <div><span className="mono">Processed</span><b>{took}</b></div>
      <div><span className="mono">Run ID</span><b>{run.run_id || "-"}</b></div>
      <div><span className="mono">Prefect flow run</span><b>{run.flow_run_id || "-"}</b></div>
    </div>
  );
}

export function Dashboard({ run, elapsed }: { run: Run; elapsed: number | null }) {
  const result = run.result!;
  return (
    <>
      <Marquee keywords={result.top_keywords} />
      <CacheSource run={run} />

      <Section num="02" title="At a glance" aside="Overview" />
      <StatTiles result={result} />

      <Section num="03" title="What it keeps saying" aside={`${result.top_keywords.length} keywords`} />
      <KeywordPanel keywords={result.top_keywords} />

      <Section num="04" title="How it sounds" aside="Tone & themes" />
      <div className="grid-2">
        <TonePanel tone={result.tone} />
        <ThemePanel themes={result.themes} />
      </div>

      <Section num="05" title="What it means" aside="Generated insights" />
      <InsightCards result={result} />

      <RawData result={result} />
      <MetaFooter run={run} elapsed={elapsed} />
    </>
  );
}
