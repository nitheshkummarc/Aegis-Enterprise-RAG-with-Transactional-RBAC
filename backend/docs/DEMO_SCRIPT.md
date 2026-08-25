# Aegis 2-Minute Demo Script

This script provides a concise, step-by-step walkthrough to demonstrate Aegis's Transactional RBAC capabilities in an interview or portfolio presentation setting.

## Prerequisites
Ensure the system is running via `docker-compose up -d --build`, then seed users and demo content:
```bash
docker-compose exec backend python -m scripts.seed_users
docker-compose exec backend python -m scripts.generate_synthetic_corpus
```
The frontend doesn't yet have a working upload UI — the "Admin Upload" badge
next to Sources is a role-conditional visual cue (`data-testid="admin-upload-btn"`
in `SourcesDropdown.tsx`), not a wired-up button. The synthetic corpus
generator is what actually seeds demo content across all three clearance
tiers, running it through the same chunking/embedding path a real upload
would (`app.ingestion.chunker`, `app.ingestion.embedder`).

---

## Step 1: Admin Data Ingestion (via the corpus generator)
1. Run the seed commands above — this creates 10 documents (4 viewer-tier, 3 manager-tier, 3 admin-tier), each chunked and embedded exactly as a real upload would be.
2. **Talking Point**: *"Ingestion — whether from a real upload or this seed script — chunks and embeds the document, and most importantly stamps `min_role_level` onto every single row in the Postgres `document_chunks` table, denormalized from the parent document."*
3. Navigate to the Aegis Frontend at `http://localhost:3000` and login as admin:
   * **Email**: `admin@clearancerag.test`
   * **Password**: `admin123`
4. Log out.

---

## Step 2: The Security Boundary (Viewer)
1. Login using the viewer credentials:
   * **Email**: `viewer@clearancerag.test`
   * **Password**: `viewer123`
2. Notice the "Admin Upload" button is absent from the UI.
3. In the chat input, ask: *"What is the CEO's total compensation for FY2025?"*
4. Observe the response: *"I do not have access to that information."*
5. Open the **Sources Dropdown** to show it is completely empty.
6. **Talking Point**: *"Because this user is a Viewer (level 0), the database physically filtered out the Admin chunks (level 2) during the vector scan. The LLM refused to answer not because it was prompted to hide it, but because the database never gave it the sensitive data in the first place. The security is enforced at the database layer."*
7. Log out.

---

## Step 3: Authorized Retrieval (Admin)
1. Login back in as the admin:
   * **Email**: `admin@clearancerag.test`
   * **Password**: `admin123`
2. In the chat input, ask the exact same question: *"What is the CEO's total compensation for FY2025?"*
3. Observe the response: The LLM answers the question accurately based on the uploaded document.
4. Open the **Sources Dropdown** to reveal the exact document chunks retrieved.
5. **Talking Point**: *"Since I am now authenticated as an Admin (level 2), the SQL query `WHERE min_role_level <= :user_role_level` allows these chunks to be passed to the LLM context. The security is seamless, verifiable, and strictly transaction-bound."*
