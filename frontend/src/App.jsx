import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ArrowRight,
  Check,
  ChevronDown,
  CircleAlert,
  Copy,
  Database,
  Download,
  Hourglass,
  LoaderCircle,
  PenLine,
  RotateCcw,
  Scale,
  Search,
  ShieldCheck,
  TriangleAlert,
  Zap,
} from "lucide-react";
import "./App.css";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
const TICKER_PATTERN = /^[A-Z]{1,5}([.-][A-Z]{1,2})?$/;
const EXAMPLES = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN"];

/* ------------------------------------------------------------------ */
/* Talking to the backend: live progress arrives as server-sent events */
/* ------------------------------------------------------------------ */
function startResearch(ticker, { onQueued, onProgress, onResult, onError }) {
  const source = new EventSource(`${API_URL}/api/research/${encodeURIComponent(ticker)}/stream`);
  let finished = false;

  const stop = () => {
    finished = true;
    source.close(); // without this the browser would reconnect and start the run again
  };
  const parse = (event) => {
    try {
      return JSON.parse(event.data);
    } catch {
      return null;
    }
  };

  source.addEventListener("queued", (e) => onQueued?.(parse(e)));
  source.addEventListener("progress", (e) => onProgress?.(parse(e)));
  source.addEventListener("result", (e) => {
    stop();
    onResult?.(parse(e));
  });
  // Our server sends "error" events with a message; a dropped connection fires one without data.
  source.addEventListener("error", (e) => {
    if (finished) return;
    stop();
    const data = e.data ? parse(e) : null;
    onError?.(data?.message || "Could not reach the FinSage server. Is it running?");
  });

  return stop;
}

/* ------------------------------------------------------------------ */
/* Splitting the Markdown brief into an intro, sections and disclaimer */
/* ------------------------------------------------------------------ */
function splitReport(markdown) {
  const parts = markdown.split(/\n(?=## )/);
  const intro = parts.shift() || "";
  const sections = parts.map((chunk) => {
    const [heading, ...rest] = chunk.split("\n");
    return { title: heading.replace(/^##\s+/, "").trim(), body: rest.join("\n").trim() };
  });

  let footer = "";
  const last = sections[sections.length - 1];
  if (last) {
    const cut = last.body.lastIndexOf("\n---");
    if (cut !== -1) {
      footer = last.body.slice(cut).replace(/^\s*-{3,}\s*/, "").replace(/\*/g, "").trim();
      last.body = last.body.slice(0, cut).trim();
    }
  }
  return { intro, sections, footer };
}

/* ------------------------------------------------------------------ */
/* Progress timeline                                                   */
/* ------------------------------------------------------------------ */
const STEP_ICONS = { start: Search, researcher: Database, analyst: Scale, writer: PenLine, verifier: ShieldCheck };
const STEP_LABELS = { start: "Starting", researcher: "Researcher", analyst: "Analyst", writer: "Writer", verifier: "Verifier" };
const NEXT_STEP = { start: "Researcher", researcher: "Analyst", analyst: "Writer", writer: "Verifier" };

function nextLabel(events) {
  const last = events[events.length - 1];
  if (!last) return "Starting";
  if (last.step === "verifier") return last.message.includes("sending") ? "Writer" : "Finishing";
  return NEXT_STEP[last.step] || "Working";
}

function Progress({ events, queued, running }) {
  return (
    <ol className="timeline" aria-live="polite">
      {queued && (
        <li className="tl-item">
          <span className="tl-icon">
            <Hourglass size={16} />
          </span>
          <div>
            <strong>Queued</strong>
            <p>{queued}</p>
          </div>
        </li>
      )}
      {events.map((e, i) => {
        const Icon = STEP_ICONS[e.step] || Search;
        return (
          <li className="tl-item" key={i}>
            <span className="tl-icon done">
              <Icon size={16} />
            </span>
            <div>
              <strong>{STEP_LABELS[e.step] || e.step}</strong>
              <p>{e.message}</p>
            </div>
            <time>{e.elapsed}s</time>
          </li>
        );
      })}
      {running && !queued && (
        <li className="tl-item working">
          <span className="tl-icon">
            <LoaderCircle size={16} className="spin" />
          </span>
          <div>
            <strong>{nextLabel(events)}</strong>
            <p>Working...</p>
          </div>
        </li>
      )}
    </ol>
  );
}

/* ------------------------------------------------------------------ */
/* The finished brief                                                  */
/* ------------------------------------------------------------------ */
const FOLDED = new Set(["Verification", "Sources"]);

const markdownComponents = {
  table: ({ node, ...props }) => (
    <div className="table-wrap">
      <table {...props} />
    </div>
  ),
  a: ({ node, ...props }) => <a {...props} target="_blank" rel="noreferrer" />,
};

function Markdown({ children }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
      {children}
    </ReactMarkdown>
  );
}

function Report({ result }) {
  const [copied, setCopied] = useState(false);
  const { intro, sections, footer } = splitReport(result.report_markdown);
  const [titleLine, ...introRest] = intro.split("\n");
  const title = titleLine.replace(/^#\s+/, "").replace(/\s*-\s*Research Brief$/, "");
  const { verified, flagged, passes } = result.verification;

  const download = () => {
    const blob = new Blob([result.report_markdown], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${result.ticker}-research-brief.md`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const copy = async () => {
    await navigator.clipboard.writeText(result.report_markdown);
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  return (
    <article className="report">
      <header className="report-head">
        <div>
          <span className="ticker-badge">{result.ticker}</span>
          <h2>{title}</h2>
        </div>
        <div className="actions">
          <button type="button" className="ghost" onClick={copy}>
            {copied ? <Check size={16} /> : <Copy size={16} />}
            {copied ? "Copied" : "Copy"}
          </button>
          <button type="button" className="ghost" onClick={download}>
            <Download size={16} />
            Download
          </button>
        </div>
      </header>

      <div className="chips">
        <span className="chip ok">
          <ShieldCheck size={14} />
          {verified} claims verified
        </span>
        {flagged > 0 && (
          <span className="chip warn">
            <TriangleAlert size={14} />
            {flagged} flagged
          </span>
        )}
        {passes.length > 1 && (
          <span className="chip">
            Passes: {passes.map((p) => `${p.flagged}/${p.total}`).join(" \u2192 ")} flagged
          </span>
        )}
        {result.cached && (
          <span className="chip">
            <Zap size={14} />
            From cache
          </span>
        )}
        <span className="chip muted">{new Date(result.generated_at).toLocaleString()}</span>
      </div>

      <div className="intro">
        <Markdown>{introRest.join("\n")}</Markdown>
      </div>

      {sections.map((s) =>
        FOLDED.has(s.title) ? (
          <details className="fold" key={s.title}>
            <summary>
              <span>{s.title}</span>
              <ChevronDown size={16} />
            </summary>
            <Markdown>{s.body}</Markdown>
          </details>
        ) : (
          <section className="block" key={s.title}>
            <h3>{s.title}</h3>
            <Markdown>{s.body}</Markdown>
          </section>
        )
      )}

      {footer && <p className="disclaimer">{footer}</p>}
    </article>
  );
}

/* ------------------------------------------------------------------ */
/* The page                                                            */
/* ------------------------------------------------------------------ */
export default function App() {
  const [ticker, setTicker] = useState("");
  const [phase, setPhase] = useState("idle"); // idle | running | done | error
  const [events, setEvents] = useState([]);
  const [queued, setQueued] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const stopRef = useRef(null);

  useEffect(() => () => stopRef.current?.(), []);

  const run = (raw) => {
    const symbol = raw.trim().toUpperCase();
    if (!TICKER_PATTERN.test(symbol)) {
      setPhase("error");
      setError("Enter a US stock ticker such as AAPL or MSFT.");
      return;
    }
    stopRef.current?.();
    setTicker(symbol);
    setPhase("running");
    setEvents([]);
    setQueued("");
    setResult(null);
    setError("");
    stopRef.current = startResearch(symbol, {
      onQueued: (d) => setQueued(d?.message || "Waiting for another report to finish."),
      onProgress: (d) => {
        setQueued("");
        setEvents((prev) => [...prev, d]);
      },
      onResult: (d) => {
        setResult(d);
        setPhase("done");
      },
      onError: (message) => {
        setError(message);
        setPhase("error");
      },
    });
  };

  const running = phase === "running";

  return (
    <div className="page">
      <header className="top">
        <span className="brand">
          <strong>Fin</strong>Sage
        </span>
        <span className="note">Educational use only</span>
      </header>

      <main className="shell">
        <section className="hero">
          <h1>
            <span className="light">Research,</span> <strong>verified.</strong>
          </h1>
          <p>
            Enter a US stock ticker. Four AI agents collect live market data, SEC filings and news,
            cross-check them, and every claim in the brief is checked against its source.
          </p>

          <form
            className="search"
            onSubmit={(e) => {
              e.preventDefault();
              run(ticker);
            }}
          >
            <input
              value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase())}
              placeholder="Ticker, for example NVDA"
              maxLength={8}
              disabled={running}
              aria-label="Stock ticker"
              autoFocus
            />
            <button type="submit" disabled={running || !ticker.trim()}>
              Research
              <ArrowRight size={16} />
            </button>
          </form>

          <div className="examples">
            {EXAMPLES.map((symbol) => (
              <button key={symbol} type="button" disabled={running} onClick={() => run(symbol)}>
                {symbol}
              </button>
            ))}
          </div>
        </section>

        {running && (
          <section className="panel">
            <h3 className="eyebrow">Working on {ticker}</h3>
            <Progress events={events} queued={queued} running={running} />
          </section>
        )}

        {phase === "error" && (
          <section className="panel error">
            <CircleAlert size={20} />
            <div>
              <strong>Something went wrong</strong>
              <p>{error}</p>
            </div>
            {TICKER_PATTERN.test(ticker) && (
              <button type="button" className="ghost" onClick={() => run(ticker)}>
                <RotateCcw size={16} />
                Try again
              </button>
            )}
          </section>
        )}

        {phase === "done" && result && <Report result={result} />}
      </main>

      <footer className="bottom">
        Built with LangGraph, MCP and FastAPI. Claims are checked automatically; this is not
        financial advice.
      </footer>
    </div>
  );
}