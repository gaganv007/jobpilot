"""Gagan's real, structured profile.

Every fact here comes from the resume / jd_agent fact sheet. Nothing is
invented. research, prep, and the packet draw only from this and the JD — they
never fabricate experience. If the JD needs something not here, it is surfaced
as a gap, not faked.
"""
from __future__ import annotations

CONTACT = {
    "name": "Gagan Veginati",
    "location": "Boston, MA (open to relocation/remote)",
    "phone": "(657) 726-5627",
    "email": "gveginati@gmail.com",
    "linkedin": "linkedin.com/in/gagan-veginati",
    "github": "github.com/gaganv007",
    "work_auth": "U.S. citizen with U.S. work authorization",
    "education": [
        "M.S. Computer Science, Boston University (2024-2026)",
        "B.Tech CS (AI/ML), SRM University AP (2020-2024)",
    ],
}

# Real STAR+R interview stories. tags drive JD-relevance selection.
STAR_STORIES: list[dict] = [
    {
        "title": "Student retention models at SRM AP",
        "situation": "As a Data Research Intern at SRM University AP, the team needed to predict which students were at risk of dropping out.",
        "task": "Build a reliable retention model over a large, messy academic dataset.",
        "action": "Engineered features and trained Random Forest, XGBoost and Logistic Regression models, comparing them and tuning the best performer over 15,000+ records.",
        "result": "Reached 89% accuracy, giving advisors an early-warning signal they could act on.",
        "reflection": "Taught me to favor the simplest model that hits the bar and to defend feature choices, not just metrics.",
        "tags": ["machine learning", "xgboost", "random forest", "classification", "data", "python", "modeling", "analytics"],
    },
    {
        "title": "5GB+ Spark ETL pipeline",
        "situation": "Data prep at SRM AP was slow and manual, blocking analysis.",
        "task": "Make ingestion of 5GB+ of data fast and repeatable.",
        "action": "Built an end-to-end pipeline with Apache Spark and Python, restructuring the transforms for parallelism.",
        "result": "Cut ETL time by 65% and made runs reproducible.",
        "reflection": "Reinforced that throughput problems are usually about the shape of the work, not raw compute.",
        "tags": ["spark", "etl", "pipeline", "data engineering", "python", "big data", "performance"],
    },
    {
        "title": "Anomaly detection + Power BI reporting",
        "situation": "Operational issues at SRM AP were being caught late and reporting was manual.",
        "task": "Surface anomalies early and give stakeholders live visibility.",
        "action": "Deployed Isolation Forest anomaly detection and built Power BI dashboards for stakeholders.",
        "result": "Flagged 150+ issues per month and replaced manual reporting with self-serve dashboards.",
        "reflection": "Showed me how much value comes from putting analysis in front of the people who act on it.",
        "tags": ["anomaly detection", "power bi", "dashboard", "analytics", "reporting", "statistics", "stakeholder", "visualization"],
    },
    {
        "title": "Gavel — live pay-per-query AI oracle",
        "situation": "I wanted a verifiable AI oracle that answers paid questions over cited sources with on-chain proof.",
        "task": "Ship a working end to end product, not a demo.",
        "action": "Built a Next.js and wagmi frontend, serverless FastAPI on AWS Lambda and API Gateway via SAM, a Bedrock failover path, a Solidity contract on Base and a custom HTTP-402 (x402) micropayment layer.",
        "result": "Resolves questions in about 14 seconds over cited sources with on-chain proof of the answer.",
        "reflection": "Taught me to integrate many moving parts under real constraints and keep latency honest.",
        "tags": ["llm", "rag", "fastapi", "aws", "lambda", "serverless", "next.js", "react", "blockchain", "solidity", "bedrock", "full stack", "api"],
    },
    {
        "title": "GNN stock movement prediction",
        "situation": "Course research project comparing graph neural networks against a baseline for next-day stock movement.",
        "task": "Test whether modeling relationships between stocks beats a flat model.",
        "action": "Implemented GCN, GraphSAGE, GAT and a Temporal-GAT versus a Random Forest baseline, with a reproducible pipeline and a Streamlit app.",
        "result": "GraphSAGE reached 58.7% next-day accuracy with an F1 of 0.654, beating the baseline.",
        "reflection": "Learned to be skeptical of flashy architectures and to report honest, reproducible numbers.",
        "tags": ["gnn", "graphsage", "pytorch", "deep learning", "machine learning", "research", "streamlit", "finance", "modeling"],
    },
    {
        "title": "ML-Blockchain MLOps platform",
        "situation": "Deploying ML plus smart-contract components together was slow and brittle.",
        "task": "Make deployment fast and repeatable.",
        "action": "Containerized the stack with Docker and Kubernetes, wrote a Python SDK and automated contract deployment.",
        "result": "3x deploy speedup and 70% less integration complexity.",
        "reflection": "Showed me the leverage of treating infra and developer experience as a product.",
        "tags": ["mlops", "devops", "docker", "kubernetes", "ci/cd", "infrastructure", "deployment", "platform", "automation"],
    },
    {
        "title": "Graduate Assistant automation at BU",
        "situation": "As a Graduate Assistant in BU CS, routine workflows for 500+ students were manual and slow.",
        "task": "Reduce manual handling and support analysis at scale.",
        "action": "Automated data processing workflows and analyzed large-scale academic datasets for 2,000+ students.",
        "result": "Cut manual handling time by 30% and supported reporting for 2,000+ students.",
        "reflection": "Reinforced that small automations compound when they touch a lot of people.",
        "tags": ["automation", "python", "data", "analytics", "workflow", "reporting"],
    },
    {
        "title": "Financial anomaly / fraud detection",
        "situation": "Imbalanced financial data made fraud-style anomalies hard to catch.",
        "task": "Detect rare events without drowning in false positives.",
        "action": "Applied SMOTE to balance classes and compared KNN, Random Forest and LSTM models.",
        "result": "Reached 95%+ F1 across the models.",
        "reflection": "Taught me to treat class imbalance as a first-class design problem.",
        "tags": ["anomaly detection", "fraud", "lstm", "machine learning", "finance", "classification", "python"],
    },
    {
        "title": "CNN facial-image classifier",
        "situation": "Computer-vision project to classify facial images accurately.",
        "task": "Build a CNN that generalizes well.",
        "action": "Designed and trained a CNN with careful augmentation and validation.",
        "result": "Reached 98.65% accuracy.",
        "reflection": "Grounded my intuition for when a model is genuinely good versus overfit.",
        "tags": ["computer vision", "cnn", "deep learning", "pytorch", "tensorflow", "machine learning"],
    },
]


def select_stories(jd_text: str, k: int = 3) -> list[tuple[dict, list[str]]]:
    """Pick the k stories whose tags best overlap the JD. Returns
    [(story, matched_tags)] sorted by overlap; ties broken by story order."""
    jl = (jd_text or "").lower()
    scored = []
    for story in STAR_STORIES:
        matched = [t for t in story["tags"] if t in jl]
        scored.append((len(matched), story, matched))
    scored.sort(key=lambda x: -x[0])
    chosen = [(s, m) for n, s, m in scored if n > 0][:k]
    if not chosen:  # JD too generic — fall back to strongest stories, honestly labeled
        chosen = [(s, []) for _, s, _ in scored[:k]]
    return chosen
