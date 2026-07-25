import re

with open("eval/run_eval.py", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Add imports
content = content.replace(
    "from sqlalchemy.orm import sessionmaker",
    "from fastapi.testclient import TestClient\nimport jwt as pyjwt\nfrom app.main import app\nfrom app.config import get_settings\nfrom sqlalchemy.orm import sessionmaker"
)

# 2. Modify run_permission_filtered_search signature
content = content.replace(
    "def run_permission_filtered_search(db, question: str, user_role: UserRole) -> list[dict]:",
    "def run_permission_filtered_search(db, question: str, user_role: UserRole) -> tuple[list[dict], float]:"
)

# 3. Add t0
content = content.replace(
    "result = db.execute(",
    "t0 = time.perf_counter()\n    result = db.execute("
)

# 4. Add t1 and latency
content = content.replace(
    "all_chunks = result.fetchall()",
    "all_chunks = result.fetchall()\n    t1 = time.perf_counter()\n    latency_ms = (t1 - t0) * 1000.0"
)

# 5. Modify return
content = content.replace(
    "        for _, c in top_chunks\n    ]",
    "        for _, c in top_chunks\n    ], latency_ms"
)

# 6. Modify run_evaluation loop body
old_loop_body = """        for q in golden_dataset:
            qid = q["id"]
            question = q["question"]
            asking_role = q["asking_role"]
            is_boundary = q.get("is_boundary_case", False)

            user_role = UserRole(asking_role)

            # Run permission-filtered search
            chunks = run_permission_filtered_search(db, question, user_role)

            # Score permission compliance"""

new_loop_body = """        latencies = []
        for q in golden_dataset:
            qid = q["id"]
            question = q["question"]
            asking_role = q["asking_role"]
            is_boundary = q.get("is_boundary_case", False)
            adv = q.get("adversarial")

            if adv in ("jwt_escalation", "jwt_null"):
                client = TestClient(app)
                fake_payload = {"sub": "admin@clearancerag.test"}
                if adv == "jwt_escalation":
                    fake_payload["role"] = "superadmin"
                else:
                    fake_payload["role"] = None
                
                token = pyjwt.encode(fake_payload, get_settings().JWT_SECRET_KEY, algorithm="HS256")
                resp = client.post("/retrieval/query", json={"question": question}, headers={"Authorization": f"Bearer "+token})
                
                chunks = []
                if resp.status_code < 400:
                    chunks = [{"title": "LEAK", "min_role_level": 999, "chunk_id": "none", "text_content": "leak", "document_id": "none", "chunk_index": 0}]
                latency_ms = 0.0
                user_role = UserRole.admin
            else:
                user_role = UserRole(asking_role)
                chunks, latency_ms = run_permission_filtered_search(db, question, user_role)
                if latency_ms > 0:
                    latencies.append(latency_ms)

            # Score permission compliance"""
content = content.replace(old_loop_body, new_loop_body)

# 7. Add latency stats to summary
old_stats = """        avg_faithfulness = (
            sum(faithfulness_scores) / len(faithfulness_scores)
            if faithfulness_scores else 0
        )

        summary = {"""
new_stats = """        avg_faithfulness = (
            sum(faithfulness_scores) / len(faithfulness_scores)
            if faithfulness_scores else 0
        )

        latencies.sort()
        avg_lat = sum(latencies) / len(latencies) if latencies else 0
        p95_idx = int(len(latencies) * 0.95) if latencies else 0
        p95_lat = latencies[p95_idx] if latencies else 0

        summary = {
            "retrieval_latency": {
                "avg_ms": round(avg_lat, 2),
                "p95_ms": round(p95_lat, 2)
            },"""
content = content.replace(old_stats, new_stats)

# 8. Add latency printing
old_print = """        print(f"  Avg Faithfulness:      {summary['faithfulness']['average_score']}")"""
new_print = old_print + """\n        print(f"  Avg Retrieval Latency: {summary['retrieval_latency']['avg_ms']}ms | p95 Retrieval Latency: {summary['retrieval_latency']['p95_ms']}ms")"""
content = content.replace(old_print, new_print)

# 9. Modify generate_markdown_report
old_markdown = """        f"| Avg Faithfulness Score | {summary['faithfulness']['average_score']} |",
        "",
        "## Permission Compliance Results","""
new_markdown = """        f"| Avg Faithfulness Score | {summary['faithfulness']['average_score']} |",
        f"| Avg Retrieval Latency | {summary['retrieval_latency']['avg_ms']}ms |",
        f"| p95 Retrieval Latency | {summary['retrieval_latency']['p95_ms']}ms |",
        "",
        "**Performance Metric:** Avg Retrieval Latency: {avg}ms \\| p95 Retrieval Latency: {p95}ms".format(
            avg=summary['retrieval_latency']['avg_ms'],
            p95=summary['retrieval_latency']['p95_ms']
        ),
        "",
        "## Permission Compliance Results","""
content = content.replace(old_markdown, new_markdown)

with open("eval/run_eval.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Patch applied.")
