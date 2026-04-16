const GITHUB_URL = "https://github.com/farawayfound/ChunkyLink";

export function About() {
  return (
    <div className="about-page">
      <h2>About ChunkyPotato</h2>

      <div className="about-panel">
        <section className="about-section">
          <h3>What this is</h3>
          <p>
            <strong>ChunkyPotato</strong> is a self-hosted{" "}
            <abbr title="Retrieval-Augmented Generation">RAG</abbr> system I built as a portfolio demo: it answers
            questions from an ingested index, adding key knowledge to the model's context window. The{" "}
            <strong>Ask Me Anything</strong> experience is grounded in a personal corpus (résumé, professional experience narratives,
            academic and personal projects); signed-in users can also upload and chat with their own documents for index building, or use
            Library to synthesize web research and import reviewed reports into Workspace.
            By default, uploaded documents and indexes are cleared on logout or after inactivity; users can explicitly enable preservation for the next session.
            The goal is to show how ingestion, NLP metadata, retrieval, safety checks, and streaming APIs fit together in a real stack—not a slide-deck
            architecture diagram. The product name is a humorous confession about where it actually runs.
          </p>
        </section>

        <section className="about-section">
          <h3>Where it runs</h3>
          <p>
            The main stack—web app, API, indexing jobs, SQLite, Redis, and the{" "}
            <strong>local LLM</strong> doing its best impression of me—lives on what can only be described as{" "}
            <strong>starch-class infrastructure</strong>: an M1 mini-PC with roughly the thermal footprint of a
            lukewarm coffee mug. There is no cloud GPU fairy. Just Ollama, patience, and silicon with ambitions
            above its station.
          </p>
          <p>
            The research pipeline has since been promoted to its own device: meet the{" "}
            <strong>Nanobot</strong>—a second machine that sits next to the first machine and is also
            not a data center. It pulls research jobs off a Redis queue, runs its own Ollama instance (
            <code className="monospace">gemma4:26b</code> with a 64k-token context window),
            crawls the web, synthesizes reports, and posts the results back over the local network. This is
            what engineers mean when they say "distributed systems." The distribution is mostly heat.
          </p>
          <p>
            If responses feel thoughtful, that may be the model reasoning—or the machine negotiating with the
            operating system for one more token. Either way: cost-effective, low-maintenance, and refreshingly
            honest about its limits.
          </p>
        </section>

        <section className="about-section">
          <h3>Architecture (high level)</h3>
          <p>
            The architecture is designed to be self-contained without cloud infrastructure or hosted LLM API access.
            It is based on a system I designed and deployed for internal use at Spectrum (Charter Communications)
            for technical debt management, extended here with a distributed research worker and a proper job queue.
          </p>
          <ul className="about-list">
            <li>
              <strong>Client</strong> — React and TypeScript (Vite); chat and research status consume
              server-sent events for streamed tokens and live phase updates (queued → crawling → synthesizing → review).
            </li>
            <li>
              <strong>API</strong> — FastAPI (Uvicorn) exposes streaming chat, document workflows, and the
              research pipeline. SQLite backs auth, invite codes, research task metadata, and operational state.
            </li>
            <li>
              <strong>Knowledge base</strong> — Chunks stored as <strong>JSONL</strong> (no separate vector database).
              Retrieval uses semantic chunk search with NLP-enriched metadata; the indexing pipeline classifies
              content, tags entities, deduplicates semantically, and links related chunks.
            </li>
            <li>
              <strong>LLM</strong> — Two <strong>Ollama</strong> instances: one on the main host for chat and
              RAG, one on the Nanobot for research synthesis. Both stream over HTTP; the backend manages
              keepalive, context windows, and model loading.
            </li>
            <li>
              <strong>RAG pipeline</strong> — Query handling → retrieval from the KB →{" "}
              <strong>relevance gating</strong> (cross-referencing, deduplication, and ranking) → prompt
              assembly → streamed answer.
            </li>
            <li>
              <strong>Research pipeline</strong> — Job submitted via API → enqueued to{" "}
              <strong>Redis Streams</strong> → Nanobot worker dequeues, searches the web, scrapes sources,
              synthesizes a markdown report via its local LLM, and posts the artifact back to the API. Status
              updates stream to the browser in real time over SSE. Reviewed reports can be imported into
              Workspace for indexing.
            </li>
            <li>
              <strong>Beyond the web UI</strong> — A <strong>Model Context Protocol (MCP)</strong> server
              exposes knowledge search, index builds, and other tools for IDE and agent workflows.
            </li>
          </ul>
        </section>

        <section className="about-section">
          <h3>Tech stack</h3>
          <p className="about-tags" aria-label="Technologies">
            Python · FastAPI · Uvicorn · httpx · React · TypeScript · Vite · Ollama · Redis Streams · spaCy (
            <code className="monospace">en_core_web_md</code>) · SQLite · JSONL knowledge store · MCP ·
            systemd (production deploy)
          </p>
        </section>

        <section className="about-section">
          <h3>Source code</h3>
          <p>
            <a className="about-github-link" href={GITHUB_URL} target="_blank" rel="noopener noreferrer">
              github.com/farawayfound/ChunkyLink
            </a>
          </p>
        </section>

        <p className="muted about-footnote">
          First-token latency is measured in “please stretch your legs” time. That is not a bug; it is the sound of
          local RAG meeting humble hardware. If the assistant pauses, it is either retrieving citations or the
          main potato is waiting on the Nanobot, which is waiting on its own Ollama, which is having a moment.
          The potatoes have unionized. They still accept coffee, but now they want it distributed across two machines.
        </p>
      </div>
    </div>
  );
}
