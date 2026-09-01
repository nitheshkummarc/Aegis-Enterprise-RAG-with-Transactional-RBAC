"""Evaluation harness for Aegis.

Usage:
    cd backend
    python -m eval.run_eval

This script:
1. Asserts the synthetic corpus is seeded (fails loudly if not)
2. Generates valid JWTs using the backend's jwt.py logic
3. Queries the /retrieval/query endpoint for each golden Q&A pair
4. Scores Faithfulness and Permission Compliance
5. Outputs results to eval/results/latest.json and docs/EVAL_RESULTS.md

CRITICAL: This uses the SAME JWT secret and creation logic as the backend.
          The JWTs are real and valid — not mocked.

Every question is run against the real pipeline:
  - permission_filtered_search runs the real SQL against real pgvector,
    using a real Groq query embedding (this is what retrieval_latency
    measures — DB time only, embedding excluded from the timer)
  - /retrieval/query is called end-to-end through the real FastAPI app
    (real embedding, real SQL, real Groq generation on GROQ_MODEL), and scoring
    is done against the LLM's actual generated text — including checking
    that boundary/refusal cases produce the exact required refusal string,
    not just that the SQL filter withheld chunks.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Ensure backend is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
import jwt as pyjwt
from app.main import app
from app.config import get_settings
from sqlalchemy.orm import sessionmaker
from app.db.session import get_engine
from app.db.models import User, UserRole, Document, DocumentChunk
from app.auth.jwt import create_access_token  # THE backend's JWT logic
from app.retrieval.search import get_role_level, permission_filtered_search
from app.retrieval.generate import active_model_name  # report the model that actually ran
from app.ingestion.embedder import embed_query, embedding_model_name

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
EVAL_DIR = Path(__file__).parent
GOLDEN_DATASET_PATH = EVAL_DIR / "golden_dataset.json"
RESULTS_DIR = EVAL_DIR / "results"
LATEST_RESULTS_PATH = RESULTS_DIR / "latest.json"
DOCS_DIR = Path(__file__).parent.parent / "docs"
EVAL_REPORT_PATH = DOCS_DIR / "EVAL_RESULTS.md"

# The exact refusal string from the system prompt (Section 5)
REFUSAL_STRING = "I do not have access to that information."


# ---------------------------------------------------------------------------
# Database checks
# ---------------------------------------------------------------------------

def assert_corpus_seeded(db) -> dict:
    """Assert the synthetic corpus is in the database. Fail loudly if not.

    Returns a dict of {title: document_id} for reference.
    """
    docs = db.query(Document).filter(Document.status == "ready").all()
    if not docs:
        raise RuntimeError(
            "FATAL: No seeded documents found in the database!\n"
            "Run: python -m scripts.generate_synthetic_corpus\n"
            "Then re-run this eval."
        )

    chunks = db.query(DocumentChunk).count()
    if chunks == 0:
        raise RuntimeError(
            "FATAL: Documents exist but no chunks found!\n"
            "The ingestion may have failed. Re-run the corpus generator."
        )

    doc_map = {doc.title: str(doc.id) for doc in docs}
    print(f"  ✓ Found {len(docs)} documents with {chunks} chunks in database.")
    return doc_map


def get_seeded_users(db) -> dict:
    """Get the seeded test users from the database.

    Returns {role_name: User} dict.
    """
    users = {}
    for role in [UserRole.viewer, UserRole.manager, UserRole.admin]:
        user = db.query(User).filter(User.role == role).first()
        if not user:
            raise RuntimeError(
                f"FATAL: No user with role '{role.value}' found!\n"
                "Run: python -m scripts.seed_users"
            )
        users[role.value] = user
    return users


# ---------------------------------------------------------------------------
# JWT generation (using the backend's ACTUAL jwt.py logic)
# ---------------------------------------------------------------------------

def generate_jwt_for_role(user: User) -> str:
    """Generate a valid JWT for a user using the backend's create_access_token.

    This is NOT a mock. It uses the same secret key and algorithm as the
    production backend, ensuring the eval queries are authenticated exactly
    like real users.
    """
    token = create_access_token({
        "sub": user.email,
        "role": user.role.value,
    })
    return token


# ---------------------------------------------------------------------------
# Real retrieval + real generation
# ---------------------------------------------------------------------------

def embed_question(question: str) -> list[float]:
    """Embed a question through the same code path the request handler uses.

    Deliberately not a second client: the harness must exercise the real
    embedder, or it would be measuring a pipeline the application does not run.
    """
    return embed_query(question)


def run_real_permission_search(
    db, query_embedding: list[float], user_role: UserRole
) -> tuple[list[dict], float]:
    """Run the real permission_filtered_search — real SQL, real pgvector
    <=> ordering, real role filter. Only the SQL execution is timed; the
    embedding call happens outside this function so the latency metric
    measures DB retrieval time, matching what the README reports."""
    t0 = time.perf_counter()
    chunks = permission_filtered_search(
        db=db, query_embedding=query_embedding, user_role=user_role, limit=3
    )
    latency_ms = (time.perf_counter() - t0) * 1000.0
    return chunks, latency_ms


def _parse_sse(response_text: str) -> dict:
    """Parse the /retrieval/query SSE stream into the full generated text,
    the final sources list, and whether a generation "error" event fired."""
    full_response = ""
    sources: list[dict] = []
    had_error_event = False

    for line in response_text.strip().split("\n"):
        line = line.strip()
        if not line.startswith("data: "):
            continue
        data_str = line[len("data: "):].strip()
        if not data_str:
            continue
        try:
            event = json.loads(data_str)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "token":
            full_response += event.get("text", "")
        elif event.get("type") == "error":
            had_error_event = True
        elif event.get("type") == "done":
            sources = event.get("sources", [])

    return {
        "full_response": full_response,
        "sources": sources,
        "had_error_event": had_error_event,
    }


def run_real_query_endpoint(client: TestClient, token: str, question: str) -> dict:
    """Call the real /retrieval/query endpoint end-to-end: real embedding,
    real SQL search, real Groq generation, real SSE stream."""
    resp = client.post(
        "/retrieval/query",
        json={"question": question},
        headers={"Authorization": f"Bearer {token}"},
    )
    result = {
        "status_code": resp.status_code,
        "full_response": "",
        "sources": [],
        "had_error_event": False,
    }
    if resp.status_code >= 400:
        return result
    result.update(_parse_sse(resp.text))
    return result


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_permission_compliance(chunks: list[dict], user_role_level: int) -> dict:
    """Score whether the SQL permission filter leaked anything above the
    asking user's role level. `chunks` come straight from
    permission_filtered_search, so min_role_level is the real DB value."""
    leaked_chunks = [c for c in chunks if c["min_role_level"] > user_role_level]

    if leaked_chunks:
        return {
            "passed": False,
            "reason": (
                f"PERMISSION LEAK! {len(leaked_chunks)} chunks with "
                f"min_role_level > {user_role_level} were returned"
            ),
            "severity": "CRITICAL",
        }

    return {
        "passed": True,
        "reason": f"No leaked chunks ({len(chunks)} permitted chunks returned)",
    }


def score_faithfulness(full_response: str, question_data: dict) -> dict:
    """Score the LLM's actual generated answer — not the retrieved chunk
    text. For boundary/refusal cases, this checks the model produced the
    exact required refusal string, not just that the SQL filter withheld
    chunks; a chunk-only check can't tell "correctly refused" apart from
    "the LLM ignored the instruction and answered anyway"."""
    if question_data.get("expected_refusal", False):
        passed = REFUSAL_STRING in full_response
        return {
            "passed": passed,
            "reason": (
                "LLM emitted the required refusal string"
                if passed
                else "LLM did NOT refuse — required refusal string missing from its answer"
            ),
            "score": 1.0 if passed else 0.0,
        }

    expected = question_data.get("expected_answer_contains", [])
    if not expected:
        return {"passed": True, "reason": "No expected content specified", "score": 1.0}

    text_lower = full_response.lower()
    found = [kw for kw in expected if kw.lower() in text_lower]
    missing = [kw for kw in expected if kw.lower() not in text_lower]
    score = len(found) / len(expected)

    return {
        "passed": score >= 0.5,
        "reason": f"Found {len(found)}/{len(expected)} expected keywords in the generated answer",
        "found": found,
        "missing": missing,
        "score": score,
    }


# ---------------------------------------------------------------------------
# Main eval loop
# ---------------------------------------------------------------------------

def run_evaluation():
    """Run the full evaluation harness."""
    print("=" * 60)
    print("Aegis — Evaluation Harness")
    print("=" * 60)

    # Load golden dataset
    with open(GOLDEN_DATASET_PATH) as f:
        golden_dataset = json.load(f)
    print(f"\nLoaded {len(golden_dataset)} questions from golden dataset.")

    # Connect to DB
    engine = get_engine()
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    settings = get_settings()
    client = TestClient(app)

    try:
        # Pre-flight checks
        print("\n[1/4] Pre-flight checks...")
        doc_map = assert_corpus_seeded(db)
        users = get_seeded_users(db)

        # Generate JWTs
        print("\n[2/4] Generating JWTs for test users...")
        jwts = {}
        for role_name, user in users.items():
            token = generate_jwt_for_role(user)
            jwts[role_name] = token
            print(f"  ✓ Generated JWT for {role_name} ({user.email})")

        # Run evaluations
        print("\n[3/4] Running evaluations against the real pipeline...")
        results = []
        permission_pass = 0
        permission_fail = 0
        permission_total = 0
        faithfulness_scores = []
        boundary_pass = 0
        boundary_fail = 0
        boundary_total = 0

        latencies = []
        for q in golden_dataset:
            qid = q["id"]
            question = q["question"]
            asking_role = q["asking_role"]
            is_boundary = q.get("is_boundary_case", False)
            adv = q.get("adversarial")

            if adv in ("jwt_escalation", "jwt_null"):
                fake_payload = {"sub": "admin@clearancerag.test"}
                fake_payload["role"] = "superadmin" if adv == "jwt_escalation" else None
                token = pyjwt.encode(
                    fake_payload, settings.JWT_SECRET_KEY, algorithm="HS256"
                )

                call = run_real_query_endpoint(client, token, question)
                # A forged token must be rejected before any chunk is ever
                # retrieved — status_code >= 400 means the auth layer
                # correctly rejected it, so no chunks could have leaked.
                chunks = (
                    []
                    if call["status_code"] >= 400
                    else [{"min_role_level": 999}]  # can't happen if auth holds
                )
                perm_result = score_permission_compliance(chunks, user_role_level=0)
                faith_result = {"passed": True, "reason": "N/A — adversarial auth case", "score": 1.0}
            else:
                user_role = UserRole(asking_role)
                user_role_level = get_role_level(user_role)
                query_embedding = embed_question(question)

                chunks, latency_ms = run_real_permission_search(
                    db, query_embedding, user_role
                )
                latencies.append(latency_ms)

                call = run_real_query_endpoint(client, jwts[asking_role], question)

                perm_result = score_permission_compliance(chunks, user_role_level)
                faith_result = score_faithfulness(call["full_response"], q)

            permission_total += 1
            if perm_result["passed"]:
                permission_pass += 1
            else:
                permission_fail += 1

            if is_boundary:
                boundary_total += 1
                if perm_result["passed"] and faith_result.get("passed", True):
                    boundary_pass += 1
                else:
                    boundary_fail += 1

            if not q.get("expected_refusal", False) and adv not in ("jwt_escalation", "jwt_null"):
                faithfulness_scores.append(faith_result["score"])

            result = {
                "id": qid,
                "question": question,
                "asking_role": asking_role,
                "is_boundary_case": is_boundary,
                "expected_refusal": q.get("expected_refusal", False),
                "sources_returned": len(call["sources"]),
                "source_titles": [s.get("title") for s in call["sources"]],
                "generated_answer": call["full_response"],
                "permission_compliance": perm_result,
                "faithfulness": faith_result,
            }
            results.append(result)

            overall_pass = perm_result["passed"] and faith_result.get("passed", True)
            status = "✓" if overall_pass else "✗"
            print(f"  {status} [{qid}] ({asking_role}) {question[:50]}...")

        # Calculate summary stats
        avg_faithfulness = (
            sum(faithfulness_scores) / len(faithfulness_scores)
            if faithfulness_scores else 0
        )

        latencies.sort()
        avg_lat = sum(latencies) / len(latencies) if latencies else 0
        p95_idx = int(len(latencies) * 0.95) if latencies else 0
        p95_lat = latencies[min(p95_idx, len(latencies) - 1)] if latencies else 0

        summary = {
            "generation_model": active_model_name(),
            "embedding_model": embedding_model_name(),
            "retrieval_latency": {
                "avg_ms": round(avg_lat, 2),
                "p95_ms": round(p95_lat, 2),
                "note": "DB-only: real pgvector <=> query time, excludes the Groq embedding call",
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_questions": len(golden_dataset),
            "permission_compliance": {
                "total": permission_total,
                "passed": permission_pass,
                "failed": permission_fail,
                "pass_rate": f"{(permission_pass / permission_total * 100):.1f}%",
            },
            "boundary_cases": {
                "total": boundary_total,
                "passed": boundary_pass,
                "failed": boundary_fail,
                "pass_rate": f"{(boundary_pass / boundary_total * 100):.1f}%" if boundary_total > 0 else "N/A",
            },
            "faithfulness": {
                "average_score": f"{avg_faithfulness:.2f}",
                "evaluated_count": len(faithfulness_scores),
                "note": "Scored against the LLM's real generated answer, not retrieved chunk text",
            },
        }

        # Save results
        print("\n[4/4] Saving results...")
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        DOCS_DIR.mkdir(parents=True, exist_ok=True)

        full_output = {"summary": summary, "results": results}

        with open(LATEST_RESULTS_PATH, "w") as f:
            json.dump(full_output, f, indent=2)
        print(f"  ✓ Results saved to {LATEST_RESULTS_PATH}")

        # Generate markdown report
        _generate_markdown_report(summary, results)
        print(f"  ✓ Report saved to {EVAL_REPORT_PATH}")

        # Print summary
        print("\n" + "=" * 60)
        print("EVALUATION SUMMARY")
        print("=" * 60)
        print(f"  Permission Compliance: {summary['permission_compliance']['pass_rate']} "
              f"({permission_pass}/{permission_total})")
        print(f"  Boundary Cases:        {summary['boundary_cases']['pass_rate']} "
              f"({boundary_pass}/{boundary_total})")
        print(f"  Avg Faithfulness:      {summary['faithfulness']['average_score']}")
        print(f"  Avg Retrieval Latency: {summary['retrieval_latency']['avg_ms']}ms | p95 Retrieval Latency: {summary['retrieval_latency']['p95_ms']}ms")

        if permission_fail > 0:
            print("\n⚠️  PERMISSION COMPLIANCE FAILURES DETECTED!")
            print("  This is a BLOCKING bug. Review the results above.")
            sys.exit(1)
        else:
            print("\n✓ All permission compliance checks PASSED.")

    finally:
        db.close()


def _generate_markdown_report(summary: dict, results: list[dict]):
    """Generate the human-readable EVAL_RESULTS.md report."""
    lines = [
        "# Aegis — Evaluation Results",
        "",
        f"**Generated**: {summary['timestamp']}",
        "",
        "This report is produced by running every golden-dataset question",
        "through the real `/retrieval/query` endpoint — real Groq",
        "embedding, real `permission_filtered_search` against pgvector,",
        f"real `{active_model_name()}` generation on Groq — and scoring against",
        "the model's actual generated answer, not the retrieved chunk text.",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Generation Model | `{summary.get('generation_model', 'unknown')}` |",
        f"| Embedding Model | `{summary.get('embedding_model', 'unknown')}` |",
        f"| Total Questions | {summary['total_questions']} |",
        f"| Permission Compliance | {summary['permission_compliance']['pass_rate']} ({summary['permission_compliance']['passed']}/{summary['permission_compliance']['total']}) |",
        f"| Boundary Cases | {summary['boundary_cases']['pass_rate']} ({summary['boundary_cases']['passed']}/{summary['boundary_cases']['total']}) |",
        f"| Avg Faithfulness Score | {summary['faithfulness']['average_score']} |",
        f"| Avg Retrieval Latency | {summary['retrieval_latency']['avg_ms']}ms |",
        f"| p95 Retrieval Latency | {summary['retrieval_latency']['p95_ms']}ms |",
        "",
        f"> Retrieval latency is DB-only ({summary['retrieval_latency']['note']}).",
        f"> Faithfulness is scored against the LLM's real answer "
        f"({summary['faithfulness']['note']}).",
        "",
        "## Permission Compliance Results",
        "",
        "| ID | Role | Boundary? | Sources | Status | Reason |",
        "|---|---|---|---|---|---|",
    ]

    for r in results:
        perm = r["permission_compliance"]
        status = "✅ PASS" if perm["passed"] else "❌ FAIL"
        boundary = "🔒 Yes" if r["is_boundary_case"] else "No"
        lines.append(
            f"| {r['id']} | {r['asking_role']} | {boundary} | "
            f"{r['sources_returned']} | {status} | {perm['reason'][:60]} |"
        )

    lines.extend([
        "",
        "## Faithfulness Results",
        "",
        "| ID | Role | Score | Found | Missing |",
        "|---|---|---|---|---|",
    ])

    for r in results:
        faith = r["faithfulness"]
        if r.get("expected_refusal"):
            status = "✅" if faith.get("passed") else "❌"
            lines.append(f"| {r['id']} | {r['asking_role']} | {status} refusal | — | — |")
        else:
            found = ", ".join(faith.get("found", []))
            missing = ", ".join(faith.get("missing", []))
            lines.append(
                f"| {r['id']} | {r['asking_role']} | {faith.get('score', 'N/A')} | "
                f"{found or '—'} | {missing or '—'} |"
            )

    lines.extend([
        "",
        "---",
        "",
        "> **Note**: Permission compliance is enforced at the database layer via",
        "> `WHERE dc.min_role_level <= :user_role_level`, verified here by calling",
        "> `permission_filtered_search` directly against the seeded synthetic",
        "> corpus. Faithfulness and refusal correctness are verified by calling",
        "> `/retrieval/query` end-to-end and checking the model's real output.",
    ])

    with open(EVAL_REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_evaluation()
