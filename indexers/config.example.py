# -*- coding: utf-8 -*-
"""
Example Configuration for vpoRAG Indexer
Copy this file to config.py and customize the paths for your environment.

NOTE: DOC_PROFILES and CONTENT_TAGS are dynamically used by the indexing system.
Modifying these will automatically update document classification and tagging behavior.
"""

# ========= DIRECTORY PATHS =========
# Source directory containing PDF and PPTX files to index
SRC_DIR = r"C:\path\to\your\documents"

# Output directory where JSON files will be created
OUT_DIR = r"C:\path\to\output\directory"

# ========= CHUNKING PARAMETERS =========
# Target size for text chunks (in tokens, ~4 chars per token)
PARA_TARGET_TOKENS = 512

# Overlap between consecutive chunks to preserve context
PARA_OVERLAP_TOKENS = 128

# Minimum chunk size to avoid creating tiny fragments
MIN_CHUNK_TOKENS = 16

# Minimum word count for a chunk to pass quality filter (0 = disabled)
CHUNK_QUALITY_MIN_WORDS = 10

# Maximum characters for router summaries
MAX_ROUTER_SUMMARY_CHARS = 3000

# Maximum depth of document hierarchy to capture (1-8)
MAX_HIERARCHY_DEPTH = 6

# ========= DEDUPLICATION SETTINGS =========
# Deduplication intensity (0-9)
# 0 = Off (no deduplication)
# 1 = Only exact duplicates (100% similar)
# 2-9 = Fuzzy matching from 97% to 76% similar (decrements of 3%)
# Recommended: 1-3 for maximum knowledge retention, 4-6 for balanced, 7-9 for aggressive deduplication
DEDUPLICATION_INTENSITY = 1

# Enable cross-file and cross-run deduplication
# When True, chunks from NEW/MODIFIED files are checked against ALL existing indexed chunks
# and against each other across different source files in the same run.
# Catches: same content in two different PDFs, re-indexed files with unchanged content,
#          and near-identical sections shared across documents.
# Performance: adds O(n*m) comparisons where n=new chunks, m=existing chunks.
# Recommended: False for first-time indexing (no existing corpus), True for incremental runs.
ENABLE_CROSS_FILE_DEDUP = False

# ========= PROCESSING OPTIONS =========
# Enable Camelot for advanced table extraction (requires Ghostscript)
# Much noisier and slower
ENABLE_CAMELOT = False

# ========= OCR SETTINGS =========
# Enable OCR for extracting text from images in PDFs, DOCX, and PPTX
ENABLE_OCR = True

# Minimum image size to process (width, height) - skips icons/logos
OCR_MIN_IMAGE_SIZE = (150, 150)

# Tesseract language codes (eng, spa, fra, deu, etc.)
# Multiple languages: 'eng+spa' for English and Spanish
OCR_LANGUAGES = 'eng'

# Number of parallel workers for OCR processing
# Recommended: 4-8 for modern CPUs (M4/12th gen i7)
PARALLEL_OCR_WORKERS = 4

# Tesseract executable path (None = auto-detect)
# Windows example: r"C:\Program Files\Tesseract-OCR\tesseract.exe"
# macOS/Linux: Usually auto-detected if installed via brew/apt
TESSERACT_PATH = r"C:\Users\PID\AppData\Local\Programs\Tesseract-OCR"

# ========= CROSS-REFERENCE SETTINGS =========
# Maximum number of related chunks to link per chunk
MAX_RELATED_CHUNKS = 5

# Minimum similarity threshold for cross-references (0.0-1.0)
MIN_SIMILARITY_THRESHOLD = 0.65

ENABLE_CROSS_REFERENCES = True

# Tags excluded from Phase 2 discovery and Phase 4 scoring during search.
# These are NLP artifacts (truncated words, path components, generic nouns)
# that appear in nearly every chunk and produce false discovery signals.
# Does NOT affect indexing — tags are still written to chunks as-is.
TAG_STOPLIST = {
    "vpo", "post", "address", "report", "communications", "client",
    "lob", "functiona", "functiona-client", "clos", "issue", "spectrum",
    "action-provide", "action-select", "action-enter", "action-configure",
    "action-check", "action-verify", "action-review", "action-update",
    "select", "select-research", "your", "home", "experience", "usage",
    "task", "escalations-usage-task", "role", "mso", "pid",
}

# Domain-specific synonym expansion (optional - leave empty for auto-generation)
# Format: {"term": ["synonym1", "synonym2", ...]}
# If empty, synonyms will be auto-generated from corpus analysis
TERM_ALIASES = {
    # Tools
    "mind-control-tool":  ["mind control", "mind control direct", "tmc tool", "stb tool", "mototerm", "pwreg", "osdiag"],
    "specnav":            ["spectrum navigator", "spec-nav", "navigator", "specnav repair tool"],
    "tmc":                ["test and measurement center", "tmcserver", "mosaic", "tmc server"],
    "scope":              ["scope.charter.com", "stb health", "stb online", "drum"],
    "emulator":           ["stva emulator", "sge", "sgui emulator", "spectrumtoolbox emulator"],
    "verbatim":           ["error code lookup", "verbatim tool", "spectrum error codes"],
    "effie":              ["effie account", "account state", "effie logs", "effie domain", "effie replay"],
    "splunk":             ["spl", "index=aws", "splunkweb", "charter splunk", "splunk query"],
    "kibana":             ["vo kibana", "elasticsearch", "ov-tune-fail", "kibana.vo"],
    "dql":                ["opensearch", "quantum kibana", "pi kibana", "opensearch dql"],
    "chrome-toolkit":     ["chrometool", "chrome tool", "avdiag", "labdiagnostic"],
    # STB hardware
    "worldbox":           ["world box", "wb", "spectrum guide box", "zodiac", "wb 1.1", "wb 2.0"],
    "xumo":               ["xione", "xumo device", "xumo box", "scxi11bei"],
    "ipstb":              ["android stb", "android ip stb", "ip set top box"],
    "docsis":             ["dsg", "cable modem", "cmts", "service group", "over docsis", "qam"],
    "dac":                ["dncs", "over qam", "qam market", "dac controller", "dncs controller"],
    # Infrastructure
    "ams":                ["activity management server", "rudp server", "ams vip", "ams oracle"],
    "csm":                ["content session manager", "avn server", "csm vip"],
    "stitcher":           ["vca", "active video", "avn cache", "av cache", "cache server"],
    "spp":                ["spectrum partner", "spp registration", "spp curl"],
    "stblookup":          ["stb lookup middle", "lineup lookup", "stblookup middle"],
    "appedge":            ["app edge", "appedge entitlements"],
    "nsm":                ["network settings middle", "networksettingsmiddle", "networksettingsuat"],
    "lrm":                ["lineup proxy", "lineup middle", "lrmmiddle", "lineup proxy service"],
    "clms":               ["channel lineup management", "channel map", "clms lineup"],
    "loginedge":          ["login edge", "login service", "loginedge cache"],
    "ipvs":               ["ip video service", "ipvs logs", "saint", "saint short circuit"],
    "epg":                ["electronic program guide", "mini guide data", "epg publishing", "epg cron", "14 days epg"],
    "cassandra":          ["cassandra db", "cqlsh", "networksettingsuat keyspace"],
    "vpns":               ["video push notification service", "push notification", "pltv vpns"],
    # Client platforms
    "stva":               ["spectrum tv app", "oneapp", "one app", "spectrum tv application"],
    "stva-roku":          ["roku stva", "stvrokursg", "roku app"],
    "stva-ios":           ["ios stva", "stvfuji", "apple tv stva", "tvos stva"],
    "stva-android":       ["android stva", "stvdroid", "oneapp-android"],
    "stva-web":           ["web stva", "stvweb", "specu", "oneapp-dotnet"],
    "cdvr":               ["cloud dvr", "cldvr", "cdvr unlimited", "cdvr nextgen", "cloud recording"],
    "pltv":               ["pause live tv", "live tv pause", "shifted linear", "pltv feature"],
    "buyflow":            ["buy flow", "upgrade flow", "ottoerr", "eligibility rate"],
    # Error codes
    "3802":               ["tune failure", "channel not available", "enhanced tuner write", "result=32777", "ov-tune-fail"],
    "rci":                ["limited mode", "restricted content interface", "spectrum tv unavailable"],
    "dywtu":              ["do you want to upgrade", "channel missing", "gold key"],
    "guide-unavailable":  ["gli-6001", "gli-6002", "ggu-6000", "ggu-6001", "ggu-7001", "ggu-7002", "ggu-7003", "3101", "guide error", "menu unavailable"],
    "gvod":               ["gvod-6012", "gvod-6016", "gvod-3026", "lscp connection failure", "service group discovery error"],
    "hdcp":               ["3804", "hdcp error", "hdcp failed", "hdcp authentication"],
    # Workflow
    "entitlements":       ["billing codes", "packages", "ace", "clm", "authorization", "billing hit", "combined entitlements"],
    "dvr":                ["recording", "cdvr", "dvr playback", "haldvr", "dvreng", "dvr service"],
    "registration":       ["registration flag", "spp registration", "reprovision", "migration flag"],
    "provisioning":       ["account standing", "account inactive", "account state", "account type"],
    "signal":             ["rf issues", "signal level", "truck roll", "plant issue"],
    "high-split":         ["hsc", "high split converter", "high-split upgrade"],
}

# ========= NLP AUTOMATION =========
# Enable automatic NLP-based classification
# True: Categories determined by content analysis (DOC_PROFILES ignored)
# False: Categories determined by filename patterns (DOC_PROFILES used)
ENABLE_AUTO_CLASSIFICATION = True

# Enable automatic NLP-based tagging
# True: Tags generated from NLP content analysis AND CONTENT_TAGS phrase matching (hybrid — recommended)
#       CONTENT_TAGS matches are always applied on top of NLP tags so domain-specific
#       tool/platform/error-code tags are never missed regardless of this setting.
# False: Tags matched using CONTENT_TAGS keyword phrases only (no NLP auto-tagging)
ENABLE_AUTO_TAGGING = True

# Maximum number of tags to add per chunk
MAX_TAGS_PER_CHUNK = 25

# ========= DOCUMENT CLASSIFICATION =========
# DOC_PROFILES: Used to classify documents by filename patterns
# Only used when ENABLE_AUTO_CLASSIFICATION = False
# Otherwise, categories are determined automatically by NLP content analysis
DOC_PROFILES = {
    "glossary": ["glossary", "acronym"],
    "slides": [".pptx"],
    "manual": ["vertical playbooks", "playbook"],
    "sop": ["creating tickets", "cross vertical"],
    "queries": ["splunk", "kibana", "queries"],
    "reference": ["reference", "guide"],
}

# CONTENT_TAGS: Domain-specific keyword phrase → tag mappings
# Always applied regardless of ENABLE_AUTO_TAGGING — these are enforced on top of NLP tags.
# When ENABLE_AUTO_TAGGING = True: merged with NLP auto-tags (hybrid mode)
# When ENABLE_AUTO_TAGGING = False: used exclusively for tagging
CONTENT_TAGS = {
    # -- TRIAGE & DIAGNOSTIC TOOLS --
    "specnav":           ["specnav", "spectrum navigator", "spec-nav", "spec nav", "navigator.prd-aws", "specnav.engprod", "specnav repair tool"],
    "mototerm":          ["mototerm", "/opt/stbtools", "stb tool 01", "stb tool 02", "ctec-stb-tool", "cmd2k mode"],
    "mind-control-tool": ["mind control", "mind control direct", "triage -> mind control", "mindcontrol", "pwreg", "osdiag", "dsgccproxy", "dc info", "silentdiag", "bootdiag", "historycmd", "dtsnvm", "dtscache", "sgd force_discovery", "sgd print", "dvreng", "haldvr", "zs *", "switchtochannel", "cas diag", "de_client", "ibtrans hist", "oobtrans hist", "rudp_stat"],
    "tmc":               ["tmc", "tmcserver", "tmc server", "tmc slot", "tmc link", "tmc map", "sword.tmcserver", "tmcserver.com", "tmc box", "tmc ticket"],
    "scope":             ["scope.charter.com", "scope search", "scope tool", "drum"],
    "emulator":          ["emulator", "sge.spectrumtoolbox.com", "stva emulator", "pilot.emu.spectrumtoolbox.com", "sgui emulator"],
    "verbatim":          ["verbatim", "verbatim.spectrumtoolbox.com", "error code lookup"],
    "quantum-tool":      ["quantum", "quantum-dashboard", "quantum-tools", "pikibana", "pi kibana", "quantumv2"],
    "ace-tool":          ["aceui", "ace tool", "ace dashboard", "aceui.prd-aws"],
    "agenos":            ["agenos", "agent os", "agen os"],
    "effie":             ["effie", "effie account", "effie logs", "effie tab", "effie domain", "effie delete domain", "effie notification", "effie replay", "effie campaign", "aws-effie", "effienotifications"],
    "chat-system":       ["chat system", "twchatapp", "chat tool"],
    "cherwell":          ["cherwell", "cherwellondemand"],
    "crescendo":         ["crescendo", "crescendo.prd-aws"],
    "alphonso":          ["alphonso", "alphonso.prd-aws"],
    "clu-tool":          ["clu tool", "clu", "channel lineup utility", "ssrs-prod2012"],
    "chrome-toolkit":    ["chrometool", "chrome tool", "chrome toolkit", "labdiagnostic.charterlab.com", "avdiag"],
    "splunk":            ["splunk", "index=aws", "index=mbo", "index=vap", "sourcetype=", "splunkweb", "splunk.chartercom.com", "charter.splunkcloud.com", "| stats", "| eval", "| rex", "| table", "| dedup", "| timechart", "| transaction", "| spath", "txnmarker=txnend", "index=aws-spec", "index=aws-stva", "index=aws-effie", "index=aws-shared", "index=app_spc"],
    "kibana":            ["kibana", "kibana.vo.charter", "vo kibana", "ov-tune-fail", "kibana.vo.charter.com"],
    "quantum-kibana":    ["pikibana", "pi kibana", "quantum kibana", "quantum-tools.spectrumtoolbox.com"],
    "datadog":           ["datadog", "datadoghq.com", "datadog dashboard"],
    "gateway":           ["charter gateway", "gateway.corp.chartercom.com"],
    "biller":            ["biller", "biller access", "billing system", "csg", "icoms"],
    "cyclops":           ["cyclops", "cyclops capabilities", "watchlive", "viewguide", "watchondemand", "insufficientcablepackage"],
    "dsb":               ["dsb", "dsb check"],
    "ovp":               ["ovp", "ovp masquerade", "ovp sender"],
    "vpns":              ["vpns", "video push notification service", "pltvschedulev1", "pltvheartbeatv1"],
    # -- STB COMMAND NAMESPACES --
    "pwreg-commands":    ["pwreg enumi", "pwreg get", "pwreg set", "pwreg forceset", "pwreg unset", "pwreg geti", "pwreg help", "pwreg get macaddress", "pwreg get boxip", "pwreg get swversion", "pwreg get dob_start", "pwreg get registration_flag", "pwreg get power_state", "pwreg get rudpserveraddress", "pwreg get avnserveraddress", "pwreg get nodeid", "pwreg set dal_group", "pwreg set registration_flag", "pwreg set migration_flag"],
    "osdiag-commands":   ["osdiag uptime", "osdiag rebootnow", "osdiag pwr-on", "osdiag c 5", "osdiag g", "osdiag reboot"],
    "silentdiag":        ["silentdiag", "silentdiag 5", "silentdiag 2", "silentdiag 1", "silentdiag all", "silentdiag 15", "silentdiag 17", "silentdiag 10", "silentdiag 19", "silentdiag 20", "silentdiag 21", "silentdiag 23", "silent diag", "dsg tunnel information"],
    "sgd-commands":      ["sgd print", "sgd force_discovery", "sgd clear", "sgd force_discovery 99", "sgd force_discovery 80", "service group discovery"],
    "dvreng-commands":   ["dvreng list-completed", "dvreng del-completed", "dvreng-list storage", "dvreng", "haldvr ls", "haldvr"],
    "dsgccproxy":        ["dsgccproxy info", "dsgccproxy", "dsg-cc", "dsg tunnel", "dsg cc proxy", "client connections"],
    "zs-commands":       ["zs *", "switchtochannel", "zs * limitedmode", "zs * dumppopups", "appcloud zs"],
    "bootdiag":          ["bootdiag status", "bootdiag", "boot summary", "boot logs", "ibtrans hist", "oobtrans hist"],
    "cas-diag":          ["cas diag", "cas provider", "emm", "ecm count", "ca system id", "ca chip", "provision status"],
    "dtsnvm":            ["dtsnvm", "dtsnvm drop", "dtsnvm dir"],
    "dtscache":          ["dtscache purge", "dtscache", "dtscache purge -1"],
    "fkps":              ["fkps", "fkps reinit", "fkps.video.ops.charter.com", "fkps set_initial_timeout", "fkps info"],
    "historycmd":        ["historycmd dump", "historycmd"],
    "de-client":         ["de_client entitlements", "de_client", "cached entitlements"],
    # -- STB HARDWARE PLATFORMS --
    "worldbox":          ["worldbox", "world box", "wb 1.1", "wb 2.0", "sp210", "sp110", "sp201", "sp101", "box model 210", "box model 110", "box model 201", "box model 101", "humax 210", "arris worldbox", "tch worldbox", "spectrum guide box", "zodiac"],
    "aloha":             ["aloha", "10.10.44", "aloha stb"],
    "hydra":             ["hydra", "cisco-hydra", "arris-hydra", "tch-hydra"],
    "arris":             ["arris", "arris e6000"],
    "humax":             ["humax", "humax 210"],
    "xumo":              ["xumo", "xione", "xumo r32", "xumo device", "xumo channel", "xumo error", "scxi11bei"],
    "ipstb":             ["ipstb", "ip stb", "android ip stb", "android stb", "android operator tier"],
    "docsis":            ["docsis", "dsg", "cmts", "service group", "docsis service group", "over docsis", "qam", "over qam", "qam market", "dac", "dncs", "edge qam", "nsg", "cmts hostname"],
    # -- INFRASTRUCTURE COMPONENTS --
    "ams":               ["ams", "rudpserveraddress", "ams ip", "ams server", "ams vip", "activity management server", "ams oracle db", "ams logs", "catalina.out", "stbcleanup", "updateepgdata", "ams cron", "pilite ams"],
    "csm":               ["csm", "content session manager", "avnserveraddress", "csm ip", "csm vip", "csmconfig"],
    "stitcher":          ["stitcher", "vca", "active video", "activevideo", "avn cache", "av cache", "cache server", "traffic_server"],
    "spp":               ["spp", "spectrum partner", "spectrum-partner.prd-aws", "spp registration", "spp curl"],
    "stblookup":         ["stblookup", "stb lookup", "stblookup middle", "stb lookup middle", "lineup_id update"],
    "appedge":           ["appedge", "app edge", "appedge/apps", "aws-appedge"],
    "nsm":               ["nsm", "network settings middle", "networksettingsmiddle", "networksettingsuat", "stbdevice table", "amsheadendmapping"],
    "lrm":               ["lrm", "lrmmiddle", "lineup proxy", "lineupproxyservice", "lineup middle", "ms clear lrm"],
    "spectrumcore":      ["spectrumcore", "spectrum-core", "spectrum core", "spectrumcore.charter.com", "getcurrentservices"],
    "cassandra":         ["cassandra", "cqlsh", "cassandra db", "epghistoricalcassandra", "networksettingsuat keyspace", "stbdevice", "dvr_recordings"],
    "clms":              ["clms", "clms-internal", "channel lineup management", "clms lineup", "channel map"],
    "loginedge":         ["loginedge", "login edge", "loginedge cache", "login curl"],
    "videocatalogedge":  ["videocatalogedge", "video catalog edge", "vce", "video catalog middle", "vcm"],
    "ipvs":              ["ipvs", "ipvs logs", "ipvs-logs", "specprod-ipvs", "saint", "saint short circuit"],
    "nile":              ["nile", "app=nile", "smarttv/stream", "liveurlfetchv4"],
    "lantern":           ["lantern", "lantern-foc-ipvs", "lantern-lrs", "lantern favorites", "lantern manifest"],
    "epgs":              ["epgs", "epg", "epg data", "epg publishing", "updateepgdata", "epg micro service", "epg cron", "epg cassandra", "mini guide data", "14 days", "epgs v4"],
    "eureka-zuul":       ["eureka", "zuul", "zuul spectrum", "pilite", "pi gateway"],
    # -- CLIENT PLATFORMS / APPS --
    "stva":              ["stva", "spectrum tv app", "spectrum tv application", "oneapp", "one app", "aws-stva", "index=aws-stva", "stvdroid", "stvfuji", "stvrokursg", "stvweb"],
    "stva-android":      ["stvdroid", "android stva", "oneapp-android"],
    "stva-ios":          ["stvfuji", "ios stva", "oneapp-ios", "tvos", "apple tv stva"],
    "stva-roku":         ["stvrokursg", "roku stva", "clienttype=roku", "oneapp-roku"],
    "stva-web":          ["stvweb", "web stva", "oneapp-dotnet", "oneapp-msa", "specu"],
    "tvsa":              ["tvsa", "tv streaming access"],
    "cdvr":              ["cdvr", "cloud dvr", "cldvr", "cdvr unlimited", "cdvr nextgen", "nns/v1/dvrmanager"],
    "pltv":              ["pltv", "pause live tv", "pltvschedulev1", "pltvrecordingurlv1", "pltvheartbeatv1", "shifted linear"],
    "buyflow":           ["buyflow", "buy flow", "ottoerr", "eligibility rate"],
    "alto":              ["alto", "alto 2.0", "alto 2.1", "alto promo"],
    # -- ERROR CODES --
    "error-3802":        ["3802", "enhanced_tuner_write", "result=32777", "tune fail", "ov-tune-fail", "channel tuning error"],
    "error-rci":         ["rci", "limited mode", "rci mode", "spectrum tv unavailable", "limitedmode reason", "nochantable"],
    "error-dywtu":       ["dywtu", "do you want to upgrade", "gold key"],
    "error-gvod":        ["gvod-6012", "gvod-6016", "gvod-3026", "gvod-6015", "lscp_connection_failure", "lscp connection"],
    "error-guide-unavailable": ["3101", "guide unavailable", "stba-3101", "stbh-3102", "avn-cl-intl", "avnan-err-stream", "avnan-err-unknown", "gli-6001", "gli-6002", "ggu-6000", "ggu-6001", "ggu-7001", "ggu-7002", "ggu-7003", "guide unavailable error", "guide info unavailable", "kigu-0001"],
    "error-8010":        ["8010", "unable to display recordings"],
    "error-gst":         ["gst-1000", "stam-1370", "stam-1130"],
    "error-3804":        ["3804", "hdcp error", "hdcp failed", "hdcp authentication"],
    "error-3016":        ["3016", "trickmoderestricted", "trick mode"],
    "error-ottoerr":     ["ottoerr", "ottoerr-006", "ottoerr-100", "ottoerr-101", "ottoerr-102", "ottoerr-104", "ottoerr-105", "ottoerr-107", "ottoerr-200"],
    # -- TICKET & WORKFLOW SYSTEMS --
    "jira":              ["jira", "jira.charter.com", "dpstriage", "postrca", "posttriage", "voguides", "sguide", "vointake", "expsi", "stvdroid", "stvfuji", "stvrokursg", "stvweb", "svzodiac", "zclient", "vpe", "posttools", "labsupreq", "speclabint"],
    "sci":               ["sci", "single customer issue", "remedy portal"],
    "inc":               ["inc creation", "create an inc", "inc template", "noc-scft"],
    "entitlements":      ["entitlement", "ace", "clm", "billing code", "billing hit", "de_client entitlements", "entitlement recalculation", "combined entitlements", "package entitlements"],
    "dvr":               ["dvr", "recording", "dvreng", "haldvr", "cdvr", "dvr playback", "dvrmiddle", "dvr service", "dvr cassandra", "dvr recordings", "dvrsupported", "no_target_program_exists"],
    "registration":      ["registration_flag", "migration_flag", "registration flag", "reprovision", "spp registration", "stb registration", "de-register"],
    "provisioning":      ["provisioning", "provisioning issue", "account standing", "account inactive", "account state", "effie account state"],
    # -- NETWORK / SIGNAL --
    "signal":            ["signal", "rf issues", "signal level", "discovery frequency", "truck roll"],
    "high-split":        ["high split", "hsc", "high-split", "high split converter"],
    "docsis-tunnel":     ["dsg tunnel", "tunnel status", "tunnel info", "silentdiag 5", "dsgccproxy info", "ca tunnel", "application tunnel", "broadcast tunnel", "tunnel present", "notstarted", "tunnel invalid"],
    # -- MICROSERVICES --
    "microservices":     ["microservice", "micro service", "ms error", "spod team", "national services", "tomcat", "tomcat7", "catalina.out", "speclabint ticket"],
    "behind-the-modem":  ["behind the modem", "behindthemodem", "behindownmodem", "btm", "behind-the-modem"],
}
