import { useState } from "react";
import { SnapIn } from "../components/SnapIn";
import { RotateIn } from "../components/RotateIn";

const LINKEDIN = "https://linkedin.com/in/david-chui-co";
const PORTFOLIO = "https://farawayfound.com";
/** Served from site root (Vite `public/` → `dist/`); same URL on macmini via FastAPI static fallback. */
const RESUME_PDF_HREF = "/DavidChui_Resume26.pdf";
const RESUME_PDF_DOWNLOAD_AS = "DavidChui_Resume26.pdf";

type ExperienceItem = {
  title: string;
  company: string;
  dates: string;
  context: string;
  summary: string;
  bullets: string[];
};

type EducationItem = {
  degree: string;
  school: string;
  year: string;
  summary: string;
  bullets?: string[];
};

const EXPERIENCE: ExperienceItem[] = [
  {
    title: "DevOps Engineer IV",
    company: "Spectrum by Charter Communications",
    dates: "October 2025 – Present",
    context:
      "Video Platform Operations team - tasked with building deployable AI tools and workflows.",
    summary:
      "Builds production AI systems for video operations: Amazon Q–based triage assistants, local LLM runtimes, MCP servers with OCR/NLP ingestion, self-learning knowledge stores, admin dashboards, and GitLab CI/CD—while mentoring teams on agentic development and presenting to senior leadership.",
    bullets: [
      "Spearheaded AI ingestion pipelines, inference integrations, and self-updating knowledge indices for agentic technical triage assistants using Amazon Q (Claude 4.6) on AWS servers.",
      "Architected a scalable, low-cost local runtime framework for LLM models, reducing token utilization from hundreds of thousands of tokens per response to user configurable limits while providing internal teams with robust, secure, highly relevant, and economical AI context.",
      "Engineered Model Context Protocol (MCP) and Agent Orchestrator physical server on intranet, automatically ingesting data from shared Knowledge Base and work notes through OCR and NLP classification and providing tool use such as Database querying and API integrations.",
      "Self-learning feature checks discovered data through triage sessions against existing indices and automatically adds version-controlled, editable chunks to a \u201clearned\u201d data store.",
      "Automated reporting to preemptively link documented bugs to reported issues before human triage, saving engineering hours, facilitating investigations, and accelerating issue resolution.",
      "Developed and scaled a data indexing framework across cross-functional teams to facilitate context enrichment and increase AI agents\u2019 usefulness and adoption.",
      "Built an administrator Dashboard to monitor MCP Server tools usage, Knowledge repository and source files management with index building options, structured database administration, client identities and authorizations, output quality monitoring, and catch warnings and errors.",
      "Deployed cronjobs to detect updates and automate database updates and index rebuilds upon changes to shared knowledge directories, empowering users to easily add knowledge to indices.",
      "Managed GitLab repositories, actions, and CI/CD pipelines to ensure automated testing and seamless deployment of new features.",
      "Championed AI-augmented development by mentoring engineering teams on prompting best practices, establishing comprehensive guidelines for AI coding, OOP principles, and security.",
      "Presented projects to Directors, Vice President of Video Products Operations, and other stakeholders from proposal/planning, POC/MVP demos, to implementation summaries.",
      "Evaluated and fine tuned Agentic assistants into daily engineering workflows, accelerating technical debt resolution and contributing to reproducible fix actions.",
      "Administered company-wide AI vector collections in Spectrum GPT.",
    ],
  },
  {
    title: "Technical Engineer II",
    company: "HomeCare HomeBase by Hearst Health",
    dates: "July 2022 – July 2025",
    context: "Product Support Tier 3: developed internal projects and tools, fixed severe escalations.",
    summary:
      "Owned full SDLC for mission-critical C#.NET healthcare systems; hybrid ServiceNow/Java/Python automation saving 500+ labor hours yearly; 30+ billable customer deliveries; and 99.9% uptime with Kubernetes, Kafka, and disciplined incident response.",
    bullets: [
      "Owned the full SDLC for C#.NET monoliths, driving change management in ServiceNow and source control in Azure DevOps.",
      "Directed the successful delivery of over 30 billable customer projects, handling the entire lifecycle from stakeholder consultation to implementation and support.",
      "Engineered a hybrid automation solution utilizing Java to interface with ServiceNow APIs and Python to execute complex compliance reporting logic, saving over 500 annual labor hours.",
      "Ensured 99.9% uptime for a healthcare platform by managing Kubernetes clusters, load balancing nodes, and resetting Kafka pods during major incidents.",
      "Architected HIPAA-compliant database environments locally and in Azure Data Warehouse, performing large-scale data migrations and merges.",
      "Resolved over 600 high-priority service requests, triaging defects and leading postmortem analysis to prevent recurring outages and production incidents.",
    ],
  },
  {
    title: "Software Engineer",
    company: "Convercent by OneTrust",
    dates: "June 2021 – July 2022",
    context: "Technical Debt Management: triaged and resolved bugs, errors, and enhancement requests.",
    summary:
      "Stabilized a .NET platform through cross-functional Agile delivery, 300+ high-quality tickets annually, GDPR-aware SQL operations, and a localization launch for 400k+ international users.",
    bullets: [
      "Facilitated cross-functional collaboration in an Agile environment to diagnose and resolve integration issues across API endpoints, Azure infrastructure, and third-party services.",
      "Designed a localization framework enabling 3 new languages for 400k+ international users.",
      "Resolved 300+ Tier 2 and Tier 4 Jira tickets, including data fixes, stored procedure optimization, and code changes with a 98% acceptance rate.",
      "Ensured GDPR compliance by running precision SQL scripts to fix data anomalies and manage the deletion of sensitive customer data.",
    ],
  },
  {
    title: "Structural Engineer",
    company: "US Air Force",
    dates: "May 2017 – April 2021",
    context:
      "Civil Engineering Squadron: maintained Nellis Air Force Base properties with multidisciplinary skills.",
    summary:
      "Led structural maintenance crews, prioritized mission-critical work, mentored junior airmen, and represented the Air Force in high-stakes ceremonial duties.",
    bullets: [
      "Managed independent crews of structural apprentices, optimizing workflow and resource allocation to maintain real property on Nellis Air Force Base.",
      "Prioritized mission-critical work according to impact and resource availability.",
      "Mentored junior airmen on technical competency and professional development.",
      "Selected for the USAF Honor Guard, leading over 35 high-stakes ceremonial events.",
    ],
  },
  {
    title: "Co-Founder, Chief Engineer",
    company: "Krate Technologies LLC",
    dates: "January 2014 – October 2016",
    context:
      "Founded start-up 3D printing, CAD, and fabrication firm aimed to fill a local need for rapid prototyping.",
    summary:
      "Co-founded a rapid-prototyping studio: owned roadmap and client delivery while adapting hands-on across CAD, fabrication, and novel engineering challenges.",
    bullets: [
      "Formulate business roadmap, manage projects from defining requirements to review.",
      "Technical expert, learning on the job daily and adapting to different problems.",
    ],
  },
];

const EDUCATION: EducationItem[] = [
  {
    degree: "Bachelor of Science in Finance & Information Systems",
    school: "University of Colorado, Denver",
    year: "2025",
    summary:
      "Strong academic record (3.8 GPA, Magna Cum Laude) blending finance with systems design, security, programming, and project delivery.",
    bullets: [
      "GPA: 3.8 | Magna Cum Laude | Applicable Coursework: System Strategy, Architecture and Design, Information Security & Privacy, Python Programming, Project Management.",
    ],
  },
  {
    degree: "Cloud Application Developer Certification",
    school: "Embry Riddle Aeronautical University",
    year: "2021",
    summary:
      "Intensive Microsoft Software and Systems Academy track focused on Azure, SQL, and C# application development.",
    bullets: ["Microsoft Software and Systems Academy 19-week course with focus on Azure, SQL, and C#."],
  },
  {
    degree: "Associate of Science in Construction Management",
    school: "Community College of the Air Force",
    year: "2020",
    summary:
      "Formal foundation in construction management emphasizing leadership and technical breadth across built environments.",
    bullets: ["Demonstrates leadership and technical excellence in the diverse fields of construction."],
  },
];

const CERTIFICATIONS = [
  "Azure Certified Developer (AZ-204, PD-900, AZ-900)",
  "Software Development C# (Microsoft)",
  "Java SE 11 Developer (Oracle)",
];

const TECHNICAL_SKILLS = {
  "Cloud/DevOps":
    "AWS, Azure, GitLab, GitHub, Terraform, Kubernetes, Docker, Rancher.",
  "Languages/Framework":
    "C#, .NET, Java, SQL, Python, Pytorch, PowerShell, Bash, JavaScript.",
  "Tools & Platforms":
    "SSMS, MongoDB, Claude Code, VS/Code, Ollama/LMS, Linux, Splunk, Jira",
};

function ExpandableCard({
  id,
  headline,
  meta,
  context,
  summary,
  bullets,
}: {
  id: string;
  headline: string;
  meta: string;
  context?: string;
  summary: string;
  bullets: string[];
}) {
  const [open, setOpen] = useState(false);
  const panelId = `${id}-details`;

  return (
    <article className="resume-card">
      <div className="resume-card__header">
        <div>
          <h3 className="resume-card__title">{headline}</h3>
          <p className="resume-card__meta">{meta}</p>
        </div>
      </div>
      {context ? <p className="resume-card__context">{context}</p> : null}
      <p className="resume-card__summary">{summary}</p>
      <button
        type="button"
        className="resume-card__toggle"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
      >
        <span className={`resume-card__chevron ${open ? "resume-card__chevron--open" : ""}`} aria-hidden>
          ▶
        </span>
        {open ? "Hide full details" : "Show full details"}
      </button>
      <div
        id={panelId}
        className={`resume-card__details ${open ? "resume-card__details--open" : ""}`}
        role="region"
        aria-label="Full résumé details"
        aria-hidden={!open}
      >
        <ul className="resume-card__bullets">
          {bullets.map((b, idx) => (
            <li key={idx}>{b}</li>
          ))}
        </ul>
      </div>
    </article>
  );
}

/* ── Stagger timing helpers ──────────────────────────────── */
const BASE_DELAY = 0;       // hero starts immediately
const TITLE_GAP = 80;       // gap between stagger groups
const CARD_STAGGER = 100;   // gap between individual cards within a section

export function MyResume() {
  // Cumulative delay tracker for cascading animations
  let d = BASE_DELAY;

  // Hero
  const heroDelay = d;
  d += 200;

  // Technical Skills title
  const skillsTitleDelay = d;
  d += TITLE_GAP;

  // Technical Skills rows (3)
  const skillEntries = Object.entries(TECHNICAL_SKILLS) as [string, string][];
  const skillDelays = skillEntries.map((_, i) => d + i * CARD_STAGGER);
  d = skillDelays[skillDelays.length - 1] + CARD_STAGGER;

  // Experience title
  const expTitleDelay = d;
  d += TITLE_GAP;

  // Experience cards (5)
  const expDelays = EXPERIENCE.map((_, i) => d + i * CARD_STAGGER);
  d = expDelays[expDelays.length - 1] + CARD_STAGGER;

  // Education title
  const eduTitleDelay = d;
  d += TITLE_GAP;

  // Education cards (3)
  const eduDelays = EDUCATION.map((_, i) => d + i * CARD_STAGGER);
  d = eduDelays[eduDelays.length - 1] + CARD_STAGGER;

  // Certifications title
  const certTitleDelay = d;
  d += TITLE_GAP;
  const certDelay = d;

  return (
    <div className="resume-page">
      {/* ── Hero ── */}
      <SnapIn from="top" delay={heroDelay}>
        <header className="resume-hero">
          <div className="resume-hero__headline">
            <h1 className="resume-hero__name">David Chui</h1>
            <a
              className="tab resume-hero__download"
              href={RESUME_PDF_HREF}
              download={RESUME_PDF_DOWNLOAD_AS}
              aria-label="Download résumé as PDF"
            >
              Download
            </a>
          </div>
          <p className="resume-hero__contact">
            <a href={PORTFOLIO} target="_blank" rel="noopener noreferrer">
              farawayfound.com
            </a>
            <span className="resume-hero__sep">|</span>
            <a href="tel:+13035202666">(303) 520-2666</a>
            <span className="resume-hero__sep">|</span>
            <a href="mailto:david.chui@outlook.com">david.chui@outlook.com</a>
            <span className="resume-hero__sep">|</span>
            <a href={LINKEDIN} target="_blank" rel="noopener noreferrer">
              linkedin.com/in/david-chui-co
            </a>
          </p>
          <p className="resume-hero__summary">
            Tenacious Software Engineer and US Air Force veteran with 5+ years of experience specializing in .NET, Azure,
            and AI-assisted development. Proven track record of leveraging large language models, advanced prompt
            engineering, and agentic coding workflows to accelerate enterprise software delivery. Passionate technologist{" "}
            skilled at designing scalable cloud architectures, translating stakeholder requirements into technical acceptance
            criteria, developing new AI tools to maximize productivity, and mentoring teams through implementation and
            adoption.
          </p>
        </header>
      </SnapIn>

      {/* ── Technical Skills ── */}
      <section className="resume-block" aria-labelledby="resume-skills-heading">
        <SnapIn from="left" delay={skillsTitleDelay}>
          <h2 id="resume-skills-heading" className="resume-block__title">
            Technical Skills
          </h2>
        </SnapIn>
        <div className="resume-skills">
          {skillEntries.map(([label, value], i) => (
            <RotateIn key={label} delay={skillDelays[i]}>
              <div className="resume-skill-row">
                <span className="resume-skill-row__label">{label}</span>
                <span className="resume-skill-row__value">{value}</span>
              </div>
            </RotateIn>
          ))}
        </div>
      </section>

      {/* ── Experience ── */}
      <section className="resume-block" aria-labelledby="resume-exp-heading">
        <SnapIn from="right" delay={expTitleDelay}>
          <h2 id="resume-exp-heading" className="resume-block__title">
            Experience
          </h2>
        </SnapIn>
        <div className="resume-stack">
          {EXPERIENCE.map((job, i) => (
            <RotateIn key={`${job.company}-${job.dates}`} delay={expDelays[i]}>
              <ExpandableCard
                id={`exp-${i}`}
                headline={`${job.title} | ${job.company}`}
                meta={job.dates}
                context={job.context}
                summary={job.summary}
                bullets={job.bullets}
              />
            </RotateIn>
          ))}
        </div>
      </section>

      {/* ── Education ── */}
      <section className="resume-block" aria-labelledby="resume-edu-heading">
        <SnapIn from="left" delay={eduTitleDelay}>
          <h2 id="resume-edu-heading" className="resume-block__title">
            Education
          </h2>
        </SnapIn>
        <div className="resume-stack">
          {EDUCATION.map((edu, i) => (
            <RotateIn key={`${edu.school}-${edu.year}`} delay={eduDelays[i]}>
              <ExpandableCard
                id={`edu-${i}`}
                headline={`${edu.degree} | ${edu.school}`}
                meta={edu.year}
                summary={edu.summary}
                bullets={edu.bullets ?? []}
              />
            </RotateIn>
          ))}
        </div>
      </section>

      {/* ── Certifications ── */}
      <section className="resume-block resume-block--last" aria-labelledby="resume-cert-heading">
        <SnapIn from="right" delay={certTitleDelay}>
          <h2 id="resume-cert-heading" className="resume-block__title">
            Certifications
          </h2>
        </SnapIn>
        <RotateIn delay={certDelay}>
          <ul className="resume-cert-list">
            {CERTIFICATIONS.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </RotateIn>
      </section>
    </div>
  );
}
