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
            <strong>Ask Me Anything</strong> experience is grounded in a personal corpus (résumé, professional expereince narratives, 
            academic and personal projects);
            signed-in users can also upload and chat with their own documents for index building. The documents and your index will be deleted after session end for your privacy and security.
            The goal is to show how ingestion, NLP metadata, retrieval, safety checks, and streaming APIs fit together in a real stack—not a slide-deck
            architecture diagram. The product name is a humorous confession about where it actually runs.
          </p>
        </section>

        <section className="about-section">
          <h3>Where it runs</h3>
          <p>
            The whole operation—web app, API, indexing jobs, SQLite, and the{" "}
            <strong>local LLM</strong> doing its best impression of me—sits on what can only be described as{" "}
            <strong>starch-class infrastructure</strong>: a mini-pc with roughly the thermal budget of a my coffee mug. There is no cloud GPU fairy; just Ollama, patience,
            and silicon with a dream. If responses feel thoughtful, that may be the model reasoning—or the
            machine taking a moment to gather enough electrons for another token. Either way, it is cost-effective,
            low-maintenance, and honest about its limits.
          </p>
        </section>

        <section className="about-section">
          <h3>Architecture (high level)</h3>
          <p>
            The architecture is designed to be easily deployable without requiring a lot of infrastructure or LLM API access.
            It is based on a system I designed and deployed for internal usage at Spectrum (Charter Communications) in technical debt maintenance.
          </p>
          <p>
            The system relies on local processing for indexing, searching, retrieval, and database tasks—bypassing the
            need for a hosted LLM API and keeping token spend small. AI agents invoke and interact with the system via
            the MCP server.
          </p>
          <ul className="about-list">
            <li>
              <strong>Client</strong> — React and TypeScript (Vite); chat consumes server-sent events for streamed
              tokens and phase updates (search vs. generation).
            </li>
            <li>
              <strong>API</strong> — FastAPI (Uvicorn) exposes streaming chat and document workflows; SQLite backs
              lightweight auth and invite codes.
            </li>
            <li>
              <strong>Knowledge base</strong> — Chunks stored as <strong>JSONL</strong> (no separate vector database).
              Retrieval uses chunk search with NLP-enriched metadata; an indexing pipeline classifies content, tags
              entities, deduplicates semantically, and links related chunks.
            </li>
            <li>
              <strong>LLM</strong> — <strong>Ollama</strong> for local inference; the backend streams responses over
              HTTP.
            </li>
            <li>
              <strong>RAG pipeline</strong> — Query handling → retrieval from the KB → <strong>relevance gating</strong>{" "}
              (symmetrical cross-referencing, deduplication, and ranking) → prompt assembly →
              streamed answer.
            </li>
            <li>
              <strong>Beyond the web UI</strong> — A <strong>Model Context Protocol (MCP)</strong> server exposes tools
              such as knowledge search, Jira search, and index builds for IDE workflows; optional Jira CSV ingestion can
              target MySQL where that integration is enabled.
            </li>
          </ul>
        </section>

        <section className="about-section">
          <h3>Tech stack</h3>
          <p className="about-tags" aria-label="Technologies">
            Python · FastAPI · Uvicorn · httpx · React · TypeScript · Vite · Ollama · spaCy (
            <code className="monospace">en_core_web_md</code>) · SQLite · JSONL knowledge store · optional MySQL · MCP ·
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
          First-token latency here is measured in “please stretch your legs” time. That is not a bug; it is the sound of
          local RAG meeting humble hardware. If the assistant pauses, assume it is either retrieving citations or
          negotiating with a very small potato for one more FLOP.
        </p>
      </div>
    </div>
  );
}
