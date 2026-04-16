import { useEffect, useRef, useState } from "react";

const LINKEDIN = "https://linkedin.com/in/david-chui-co";

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
      "Builds production AI systems for video operations: Amazon Q–based triage assistants, local LLM runtimes, MCP servers with OCR/NLP indexing, self-learning knowledge bases, admin dashboards, and GitLab CI/CD—while mentoring teams on agentic development and presenting to senior leadership.",
    bullets: [
      "Spearheaded AI ingestion pipelines, inference integrations, and self-updating knowledge indices for agentic technical triage assistants using Amazon Q (Claude 4.6) on AWS servers.",
      "Architected a scalable, low-cost local runtime framework for LLM models, reducing token utilization from hundreds of thousands of tokens per response to user configurable limits while providing internal teams with robust, secure, highly relevant, and economical AI context.",
      "Engineered Model Context Protocol (MCP) and Agent Orchestrator physical server on intranet, automatically indexing data from shared Knowledge Base and work notes through OCR and NLP classification and providing tool use such as Database querying and API integrations.",
      "Self-learning feature checks discovered data through triage sessions against existing indices and automatically adds version-controlled, managed chunks to a “learned” index.",
      "Built an administrator Dashboard to monitor MCP Server tools usage, Knowledge repository and source files management with index building options, structured database administration, client identities and authorizations, output quality monitoring, and catch warnings and errors.",
      "Deployed cronjobs to detect updates and automate database updates and index rebuilds.",
      "Administered the GitLab repository and CI/CD pipelines to ensure automated testing and seamless deployment of new features.",
      "Championed AI-augmented development by mentoring engineering teams on prompting best practices, establishing comprehensive guidelines for AI coding, OOP principles, and security.",
      "Presented projects to Directors, Vice President of Video Products Operations, and other stakeholders from proposal/planning, POC/MVP demos, to implementation summaries.",
      "Evaluated and fine tuned Agentic assistants into daily engineering workflows, accelerating technical debt resolution and contributing to reproducible fix actions.",
      "Worked around constraints using routed and categorized JSON indices with symmetrical cross-referencing and configuring dual mode (local or MCP) searches based on access level.",
      "Managed system health monitoring and Log Analysis through enterprise toolsets to ensure platform stability and proactive issue detection.",
      "Triaged executive escalations and high complexity technical debt: translating high-pressure incidents into clear postmortem analysis and strategic resolution roadmaps.",
    ],
  },
  {
    title: "Technical Engineer II",
    company: "HomeCare HomeBase by Hearst Health",
    dates: "July 2022 – July 2025",
    context: "Product Support Tier 3: developed internal projects and tools, fixed severe escalations.",
    summary:
      "Owned full SDLC for a mission-critical C#.NET healthcare stack; automated compliance and operations (ServiceNow, PowerShell/Python, T-SQL) saving 500+ labor hours yearly; delivered 30+ billable customer engagements; and held 99.9% uptime with Kubernetes, Kafka, and disciplined postmortems.",
    bullets: [
      "Drove end-to-end SDLC for C#.NET monolith enhancements and critical fixes—requirements through production—with ServiceNow change management and Azure DevOps delivery.",
      "Strengthened reliability using Splunk and Azure Data Warehouse to trace .NET and SQL exceptions, eliminate root causes, and avoid regressions on complex dependencies.",
      "Sustained 99.9% uptime via Kubernetes and Kafka operations during major incidents, plus documented postmortems and preventive hardening.",
      "Built HIPAA-compliant database patterns and executed large-scale migrations and merges in Azure Data Warehouse with query and distribution tuning for cost and performance.",
      "Saved 500+ annual labor hours automating compliance reporting through ServiceNow APIs combined with PowerShell, Python, and advanced T-SQL.",
      "Led 30+ billable customer projects from stakeholder scoping through go-live and post-deployment support, keeping timelines and quality aligned.",
      "Closed 600+ high-priority service requests while capturing repeatable fixes and documentation that scaled junior engineers and cut repeat escalations.",
    ],
  },
  {
    title: "Software Engineer",
    company: "Convercent by OneTrust",
    dates: "June 2021 – July 2022",
    context: "Technical Debt Management: triaged and resolved bugs, errors, and enhancement requests.",
    summary:
      "Stabilized a .NET platform through 300+ high-quality tickets annually, GDPR-aware SQL operations, cross-stack diagnostics, internal enablement for Tier 1/CSM, and a localization launch for 400k+ international users.",
    bullets: [
      "Resolved 300+ Tier 2 and Tier 4 Jira tickets annually—including data fixes, stored procedure tuning, and code changes—with a 98% acceptance rate via Visual Studio and Azure DevOps sprints.",
      "Protected customer trust with precision SQL remediation, controlled sensitive deletions, and validation aligned to GDPR expectations.",
      "Diagnosed complex defects across APIs, Azure services, and third-party integrations using browser tooling, Postman, SendGrid, and Azure observability with SME collaboration.",
      "Published reusable templates, scripts, and knowledge articles so Tier 1 and Customer Success closed recurring issues without engineering escalations.",
      "Shipped a localization framework that introduced three new languages for 400,000+ international users.",
    ],
  },
  {
    title: "Structural Engineer",
    company: "US Air Force",
    dates: "May 2017 – April 2021",
    context:
      "Civil Engineering Squadron: maintained Nellis Air Force Base real property across structural trades.",
    summary:
      "Rotated through sheet metal, welding, carpentry, masonry, locksmithing, roofing, flooring, and finish work; led crews; mentored junior airmen; supported standby and ceremonial duties; and delivered visible squadron legacy projects.",
    bullets: [
      "Led independent crews of three, optimizing workflows, delegating by proficiency, and prioritizing mission-critical work orders against resource limits.",
      "Rotated quarterly across trades to sustain versatility maintaining base infrastructure in extreme operational conditions.",
      "Stood one-week alert rotations every eight weeks—reachable within an hour—to support emergency response for breached perimeters and facility crises.",
      "Mentored junior airmen on technical skills and professional growth away from home station.",
      "USAF Honor Guard and Color Guard: executed 35+ high-stakes events, including 27 funeral ceremonies with firing party and pallbearer duties and eight major Las Vegas processions.",
      "Designed and led a 15-foot mural at Lackland basic training lecture halls and created the 99th Civil Engineering Squadron commemorative coin.",
    ],
  },
  {
    title: "Wedding Photographer",
    company: "Agaba Studios",
    dates: "February 2016 – February 2017",
    context: "Houston, TX — wedding and portrait photography with direct client ownership.",
    summary:
      "Partnered with couples on full wedding-day coverage, directed large groups on-site, and balanced studio assignments with independent creative work.",
    bullets: [
      "Delivered 12 weddings and 15 engagement sessions with structured planning, timeline control, and consistent client communication.",
      "Directed large groups across venues to capture essential moments efficiently while maintaining a calm, service-oriented presence.",
      "Produced independent landscape, portrait, and senior photography projects alongside studio commitments.",
    ],
  },
  {
    title: "Co-Founder, Chief Technology Officer",
    company: "Krate Technologies LLC",
    dates: "December 2013 – October 2016",
    context:
      "Agile 3D printing, CAD, and fabrication studio serving B2B/B2C clients with rapid prototypes and embedded (Arduino) solutions.",
    summary:
      "Co-founded a rapid-prototyping startup: owned roadmap and delivery, mentored a tiny technical team, and shipped high-touch hardware projects from Maker’s Cafe operations.",
    bullets: [
      "Defined the roadmap and ran projects from requirements through client review with short feedback loops and integrated operations.",
      "Delivered notable builds including architectural models for Matt Fajkus Architecture, research-oriented 3D scanning for UT/Blanton Museum collaborators, and complex wearable/mechanical prototypes.",
      "Operated as hands-on CTO across CAD, FDM printing, and Arduino-backed embedded work, adapting quickly to novel fabrication challenges.",
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

function useRevealOnScroll() {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const root = ref.current;
    if (!root) return;

    const els = root.querySelectorAll<HTMLElement>("[data-reveal]");
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("resume-reveal--visible");
            observer.unobserve(entry.target);
          }
        });
      },
      { root: null, rootMargin: "0px 0px -8% 0px", threshold: 0.08 },
    );

    els.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, []);

  return ref;
}

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

export function MyResume() {
  const containerRef = useRevealOnScroll();

  return (
    <div className="resume-page" ref={containerRef}>
      <header className="resume-hero">
        <h1 className="resume-hero__name">David Chui</h1>
        <p className="resume-hero__contact">
          <span>Denver, CO</span>
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
          Tenacious Software Engineer and US Air Force veteran with 7+ years of experience specializing in .NET, Azure,
          and AI integrations. Proven track record of leveraging llm's, knowlege ingestion prompt
          engineering, and agentic workflows to accelerate enterprise software delivery. Passionate technologist 
          skilled at designing scalable cloud architectures, translating stakeholder requirements into
          technical acceptance criteria, developing new AI tools to maximize productivity, and mentoring teams through
          implementation and adoption.
        </p>
      </header>

      <section className="resume-block" data-reveal aria-labelledby="resume-skills-heading">
        <h2 id="resume-skills-heading" className="resume-block__title">
          Technical Skills
        </h2>
        <div className="resume-skills">
          {(Object.entries(TECHNICAL_SKILLS) as [string, string][]).map(([label, value]) => (
            <div key={label} className="resume-skill-row">
              <span className="resume-skill-row__label">{label}</span>
              <span className="resume-skill-row__value">{value}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="resume-block" data-reveal aria-labelledby="resume-exp-heading">
        <h2 id="resume-exp-heading" className="resume-block__title">
          Experience
        </h2>
        <div className="resume-stack">
          {EXPERIENCE.map((job, i) => (
            <ExpandableCard
              key={`${job.company}-${job.dates}`}
              id={`exp-${i}`}
              headline={`${job.title} | ${job.company}`}
              meta={job.dates}
              context={job.context}
              summary={job.summary}
              bullets={job.bullets}
            />
          ))}
        </div>
      </section>

      <section className="resume-block" data-reveal aria-labelledby="resume-edu-heading">
        <h2 id="resume-edu-heading" className="resume-block__title">
          Education
        </h2>
        <div className="resume-stack">
          {EDUCATION.map((edu, i) => (
            <ExpandableCard
              key={`${edu.school}-${edu.year}`}
              id={`edu-${i}`}
              headline={`${edu.degree} | ${edu.school}`}
              meta={edu.year}
              summary={edu.summary}
              bullets={edu.bullets ?? []}
            />
          ))}
        </div>
      </section>

      <section className="resume-block resume-block--last" data-reveal aria-labelledby="resume-cert-heading">
        <h2 id="resume-cert-heading" className="resume-block__title">
          Certifications
        </h2>
        <ul className="resume-cert-list">
          {CERTIFICATIONS.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      </section>
    </div>
  );
}
