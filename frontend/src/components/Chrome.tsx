import type { ReactNode } from "react";
import { API_BASE } from "../api";

export function Nav({ online }: { online: boolean | null }) {
  return (
    <div className="nav">
      <div className="brand">
        <span className="brand-mark" />
        textlens
      </div>
      <div className="pill" title={API_BASE}>
        {online === false ? (
          <><span className="dot bad" />API offline</>
        ) : (
          <><span className="dot good" />{online ? "API connected" : "Checking API"}</>
        )}
      </div>
    </div>
  );
}

export function Hero() {
  return (
    <div className="hero">
      <div className="eyebrow">Text intelligence · NLTK · Prefect · Redis</div>
      <h1>
        <span className="reveal">Read</span>{" "}
        <span className="reveal"><em>between</em></span>{" "}
        <span className="reveal">the lines.</span>
      </h1>
      <div className="hero-foot">
        <p className="lede">
          Drop in any plain-text file. We count it, find what it keeps returning to, read its tone
          and surface the themes underneath.
        </p>
        <div className="specs">
          <div><span className="mono">Format</span><b>.txt · UTF-8</b></div>
          <div><span className="mono">Limit</span><b>5 MB</b></div>
          <div><span className="mono">Output</span><b>Live dashboard</b></div>
        </div>
      </div>
    </div>
  );
}

export function Section({ num, title, aside }: { num: string; title: string; aside?: ReactNode }) {
  return (
    <div className="section-head">
      <span className="num">{num}</span>
      <h2>{title}</h2>
      {aside && <div className="aside mono">{aside}</div>}
    </div>
  );
}

export function Notice({ title, body }: { title: string; body: string }) {
  return (
    <div className="notice" role="alert">
      <span className="icon">✕</span>
      <div><b>{title}</b>{body}</div>
    </div>
  );
}

export function Colophon() {
  return (
    <div className="colophon">
      <div className="big">textlens<span style={{ color: "var(--accent)" }}>.</span></div>
      <div style={{ alignSelf: "end", textAlign: "right" }}>
        FastAPI · Prefect · Redis · NLTK<br />Built for reading text at a glance.
      </div>
    </div>
  );
}

export function Toast({ message, kind }: { message: string; kind: "info" | "error" }) {
  return <div className={`toast ${kind}`} role="status">{message}</div>;
}
