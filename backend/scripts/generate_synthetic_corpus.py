"""Generate synthetic corpus for Nexus Logistics across 3 role tiers.

Usage:
    cd backend
    python -m scripts.generate_synthetic_corpus

Creates text documents with content appropriate to each clearance level
and runs a cross-contamination check to ensure lower-tier docs do not
contain high-tier keywords.
"""

import sys
import os
import json
import uuid
from pathlib import Path

# Ensure the backend directory is on the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Cross-contamination keyword sets
# ---------------------------------------------------------------------------

# Keywords that MUST NOT appear in viewer-tier (level 0) documents
ADMIN_ONLY_KEYWORDS = {
    "revenue", "salary", "compensation", "m&a", "merger", "acquisition",
    "acquisition target", "ipo", "equity", "stock option", "board resolution",
    "executive pay", "severance", "termination package", "confidential",
    "restricted", "classified", "top secret",
}

# Keywords that MUST NOT appear in viewer-tier documents (manager+admin only)
MANAGER_ONLY_KEYWORDS = {
    "quarterly target", "pipeline forecast", "conversion rate",
    "sales quota", "headcount plan", "budget allocation", "roi projection",
    "competitive analysis", "market penetration", "pricing strategy",
}


# ---------------------------------------------------------------------------
# Synthetic document content by role tier
# ---------------------------------------------------------------------------

VIEWER_DOCUMENTS = [
    {
        "title": "Nexus Logistics — Employee Handbook (Public)",
        "min_role_level": 0,
        "content": (
            "Welcome to Nexus Logistics! This handbook outlines our company policies "
            "for all employees. Our standard working hours are 9 AM to 6 PM, Monday "
            "through Friday. Employees receive 15 days of paid time off per year, "
            "plus 10 public holidays. The dress code is business casual for office "
            "staff and safety gear for warehouse personnel. All employees must complete "
            "the onboarding training within their first 30 days. Our office locations "
            "include Chicago (HQ), Dallas, and Seattle. The cafeteria is open from "
            "7 AM to 7 PM and offers subsidized meals. Parking is available on a "
            "first-come, first-served basis in the main lot. For IT support, contact "
            "helpdesk@nexuslogistics.com or dial extension 4400. Our company was "
            "founded in 2012 and currently employs over 2,500 people across three "
            "regional hubs. We specialize in last-mile delivery for e-commerce "
            "partners. Our core values are Safety, Speed, and Service."
        ),
    },
    {
        "title": "Nexus Logistics — Warehouse Safety Guidelines",
        "min_role_level": 0,
        "content": (
            "All warehouse personnel must wear steel-toed boots, high-visibility vests, "
            "and hard hats while on the floor. Forklift operation requires certification "
            "renewed annually. Maximum pallet stacking height is 4 meters. Emergency "
            "exits are located at the north and south ends of each warehouse bay. Fire "
            "extinguishers are inspected monthly and are located every 15 meters along "
            "the main aisles. Incident reports must be filed within 24 hours of any "
            "workplace injury. The safety committee meets bi-weekly to review incidents "
            "and near-misses. Speed limit for forklifts inside the warehouse is 8 km/h. "
            "Loading dock doors must remain closed when not in active use to maintain "
            "temperature control. All new hires complete a 2-day safety orientation "
            "before starting floor duties."
        ),
    },
    {
        "title": "Nexus Logistics — IT Acceptable Use Policy",
        "min_role_level": 0,
        "content": (
            "Company devices are for business use only. Personal use of company email "
            "is discouraged. All employees must use two-factor authentication for "
            "internal systems. Passwords must be at least 12 characters and changed "
            "every 90 days. USB drives are prohibited on company machines without IT "
            "approval. VPN must be used when accessing internal systems remotely. "
            "Report any suspicious emails to security@nexuslogistics.com immediately. "
            "Software installation requires IT department approval. Data must not be "
            "stored on personal cloud services. Company laptops are encrypted with "
            "BitLocker. The IT department performs quarterly security audits."
        ),
    },
    {
        "title": "Nexus Logistics — Customer Service Procedures",
        "min_role_level": 0,
        "content": (
            "All customer inquiries must be acknowledged within 2 hours during business "
            "hours. Delivery complaints should be escalated to the regional hub manager "
            "if unresolved within 24 hours. Refund requests for damaged goods require "
            "photographic evidence and must be processed within 5 business days. The "
            "customer satisfaction target is a Net Promoter Score of 45 or above. "
            "Phone support operates from 8 AM to 8 PM in each time zone. Chat support "
            "is available 24/7 via the website. Standard delivery SLA is 2-3 business "
            "days for metro areas and 5-7 business days for rural regions."
        ),
    },
]

MANAGER_DOCUMENTS = [
    {
        "title": "Nexus Logistics — Q3 2025 Regional Performance Summary",
        "min_role_level": 1,
        "content": (
            "Q3 Regional Performance Summary (Manager Internal Only). The Chicago hub "
            "processed 1.2 million packages in Q3, a 12% increase over Q2. The Dallas "
            "hub saw a 3% decline due to the August heatwave causing fleet downtime. "
            "Seattle maintained steady throughput at 800K packages. Our quarterly target "
            "of 3 million total packages was met at 3.05M. The pipeline forecast for Q4 "
            "shows projected volume of 3.8M due to holiday season. Headcount plan calls "
            "for 200 seasonal hires across all three hubs. Budget allocation for Q4 "
            "marketing is set at $450K, up from $300K in Q3. Conversion rate from "
            "trial partners to full contracts improved to 34%. Competitive analysis "
            "shows our main rival, SwiftShip, expanding into the Midwest."
        ),
    },
    {
        "title": "Nexus Logistics — Fleet Management Dashboard Brief",
        "min_role_level": 1,
        "content": (
            "Fleet utilization averaged 78% in September, below our 85% target. "
            "Maintenance costs per vehicle increased 8% year-over-year due to aging "
            "fleet. The pricing strategy for B2B contracts is under review — current "
            "tiered model may need adjustment for high-volume clients. ROI projection "
            "for the electric vehicle pilot shows breakeven at 18 months. Driver "
            "retention rate is 82%, above industry average of 74%. Route optimization "
            "software reduced average delivery time by 11 minutes per route. Fuel costs "
            "represent 23% of total operational expenditure. Market penetration in the "
            "Southeast region remains at 6%, below our 10% target for year-end."
        ),
    },
    {
        "title": "Nexus Logistics — Team Performance Review Framework",
        "min_role_level": 1,
        "content": (
            "Managers must complete performance reviews for all direct reports by the "
            "end of each quarter. Reviews include metrics on delivery accuracy, "
            "attendance, and customer feedback scores. Sales quota attainment is tracked "
            "weekly and reported in the Monday dashboard. Underperforming team members "
            "receive a 30-day improvement plan with bi-weekly check-ins. Promotion "
            "decisions are finalized in the annual talent review held every January. "
            "Cross-training between departments is encouraged to build bench strength. "
            "The new competency framework includes five dimensions: Technical Skills, "
            "Leadership, Collaboration, Customer Focus, and Innovation."
        ),
    },
]

ADMIN_DOCUMENTS = [
    {
        "title": "Nexus Logistics — Executive Compensation & Equity Plan",
        "min_role_level": 2,
        "content": (
            "CONFIDENTIAL — Executive Eyes Only. CEO total compensation for FY2025 is "
            "$2.8M base salary plus $1.5M performance bonus and 500,000 stock options "
            "vesting over 4 years. CFO compensation is $1.9M base with $800K bonus. "
            "The board resolution dated March 15, 2025 approved the revised executive "
            "pay structure. VP-level equity grants range from 50,000 to 150,000 options. "
            "Severance packages for C-suite include 24 months base salary plus "
            "accelerated vesting. The termination package for the former COO totaled "
            "$4.2M including all benefits. Executive pay benchmarking was conducted by "
            "Willis Towers Watson against a peer group of 15 logistics companies."
        ),
    },
    {
        "title": "Nexus Logistics — M&A Strategy Briefing (Board Confidential)",
        "min_role_level": 2,
        "content": (
            "CLASSIFIED — Board Members Only. Nexus Logistics is evaluating two "
            "acquisition targets for Q1 2026. Target Alpha is a regional last-mile "
            "carrier in the Southeast with annual revenue of $180M and 1,200 employees. "
            "Estimated acquisition cost is $450M at 2.5x revenue multiple. Target Beta "
            "is a technology platform for route optimization with $30M annual revenue. "
            "The merger integration timeline is estimated at 18 months. IPO preparation "
            "is on track for H2 2026 with Goldman Sachs as lead underwriter. Pre-IPO "
            "valuation range is $3.2B to $3.8B. Revenue for FY2025 is projected at "
            "$1.1B, up 22% year-over-year. The M&A committee meets monthly to review "
            "due diligence progress."
        ),
    },
    {
        "title": "Nexus Logistics — Board Financial Summary FY2025",
        "min_role_level": 2,
        "content": (
            "RESTRICTED — Board Eyes Only. Total revenue for FY2025 reached $1.1B, "
            "exceeding the $1.05B target. EBITDA margin expanded to 14.2% from 12.8% "
            "in FY2024. Net income was $98M after tax. The company holds $220M in cash "
            "reserves. Long-term debt stands at $340M following the Q2 refinancing at "
            "5.2% fixed rate. Capital expenditure for FY2025 totaled $85M, primarily "
            "for fleet expansion and warehouse automation. Shareholder equity increased "
            "to $780M. The board approved a $50M share buyback program for FY2026. "
            "Salary costs represent 38% of total operating expenses."
        ),
    },
]

ALL_DOCUMENTS = VIEWER_DOCUMENTS + MANAGER_DOCUMENTS + ADMIN_DOCUMENTS


# ---------------------------------------------------------------------------
# Cross-contamination check
# ---------------------------------------------------------------------------

def check_cross_contamination(documents: list[dict]) -> None:
    """Scan lower-tier documents for keywords that belong to higher tiers.

    Raises ValueError immediately if contamination is detected.
    This is the defensible proof of data hygiene required by Section 7.
    """
    violations = []

    for doc in documents:
        content_lower = doc["content"].lower()
        title = doc["title"]
        level = doc["min_role_level"]

        # Viewer docs (level 0) must NOT contain admin or manager keywords
        if level == 0:
            for kw in ADMIN_ONLY_KEYWORDS | MANAGER_ONLY_KEYWORDS:
                if kw.lower() in content_lower:
                    violations.append(
                        f"CONTAMINATION: Viewer doc '{title}' contains "
                        f"restricted keyword '{kw}'"
                    )

        # Manager docs (level 1) must NOT contain admin-only keywords
        elif level == 1:
            for kw in ADMIN_ONLY_KEYWORDS:
                if kw.lower() in content_lower:
                    violations.append(
                        f"CONTAMINATION: Manager doc '{title}' contains "
                        f"admin-only keyword '{kw}'"
                    )

    if violations:
        error_msg = "Cross-contamination detected!\n" + "\n".join(violations)
        raise ValueError(error_msg)

    print("  [OK] Cross-contamination check passed - no keyword leaks detected.")


# ---------------------------------------------------------------------------
# Database seeding
# ---------------------------------------------------------------------------

def seed_synthetic_corpus() -> dict:
    """Seed the synthetic corpus into the database.

    Returns a dict mapping document titles to their DB IDs.
    """
    from sqlalchemy.orm import sessionmaker
    from app.db.session import get_engine
    from app.db.models import User, UserRole, Document, DocumentChunk
    from app.core.security import hash_password
    from app.ingestion.chunker import chunk_text
    from app.ingestion.embedder import embed_texts

    engine = get_engine()
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    try:
        # Ensure admin user exists for uploaded_by FK
        admin = db.query(User).filter(User.role == UserRole.admin).first()
        if not admin:
            admin = User(
                email="admin@clearancerag.test",
                password_hash=hash_password("admin123"),
                role=UserRole.admin,
            )
            db.add(admin)
            db.commit()
            db.refresh(admin)
            print(f"  Created admin user: {admin.email}")

        doc_id_map = {}

        for doc_data in ALL_DOCUMENTS:
            # Check if document already exists
            existing = db.query(Document).filter(
                Document.title == doc_data["title"]
            ).first()
            if existing:
                print(f"  Document '{doc_data['title']}' already exists, skipping.")
                doc_id_map[doc_data["title"]] = str(existing.id)
                continue

            # Create document
            doc = Document(
                title=doc_data["title"],
                uploaded_by=admin.id,
                min_role_level=doc_data["min_role_level"],
                status="ready",
            )
            db.add(doc)
            db.flush()  # Get the ID

            # Chunk the content
            chunks = chunk_text(doc_data["content"], chunk_size=500, chunk_overlap=50)

            # Real embeddings via the same path production ingestion uses.
            # Uniform placeholder vectors would make cosine similarity
            # identical across every chunk, so a query embedding couldn't
            # actually retrieve the relevant chunk — fine for exercising
            # the permission filter alone, but not for an eval that also
            # scores retrieval/generation faithfulness end-to-end.
            embeddings = embed_texts(chunks)

            for i, (chunk_content, embedding) in enumerate(zip(chunks, embeddings)):
                chunk = DocumentChunk(
                    document_id=doc.id,
                    chunk_index=i,
                    text_content=chunk_content,
                    embedding=embedding,
                    min_role_level=doc.min_role_level,
                )
                db.add(chunk)

            doc_id_map[doc_data["title"]] = str(doc.id)
            print(
                f"  Seeded: '{doc_data['title']}' "
                f"(level={doc_data['min_role_level']}, chunks={len(chunks)})"
            )

        db.commit()
        return doc_id_map

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("Nexus Logistics — Synthetic Corpus Generator")
    print("=" * 60)

    print("\n[1/2] Running cross-contamination check...")
    check_cross_contamination(ALL_DOCUMENTS)

    print("\n[2/2] Seeding documents into database...")
    doc_ids = seed_synthetic_corpus()

    print(f"\n[OK] Done. Seeded {len(doc_ids)} documents.")
    print("\nDocument ID mapping:")
    for title, doc_id in doc_ids.items():
        print(f"  {title}: {doc_id}")
