"""Integration tests for GET /documents/ RBAC filtering."""

import pytest

from app.auth.jwt import create_access_token
from app.db.models import Document


class TestListDocumentsRBAC:
    """Tests for GET /documents/."""

    def _get_auth_header(self, email: str, role: str) -> dict:
        token = create_access_token({"sub": email, "role": role})
        return {"Authorization": f"Bearer {token}"}

    @pytest.fixture()
    def seeded_documents(self, db_session, admin_user):
        """Create one document at each role tier."""
        viewer_doc = Document(
            title="Employee Handbook",
            uploaded_by=admin_user.id,
            min_role_level=0,
            status="ready",
        )
        manager_doc = Document(
            title="Q3 Roadmap",
            uploaded_by=admin_user.id,
            min_role_level=1,
            status="ready",
        )
        admin_doc = Document(
            title="Executive Compensation",
            uploaded_by=admin_user.id,
            min_role_level=2,
            status="ready",
        )
        db_session.add_all([viewer_doc, manager_doc, admin_doc])
        db_session.commit()
        return {
            "viewer_doc": viewer_doc,
            "manager_doc": manager_doc,
            "admin_doc": admin_doc,
        }

    def test_viewer_only_sees_viewer_tier_documents(
        self, client, viewer_user, seeded_documents
    ):
        headers = self._get_auth_header(viewer_user.email, "viewer")
        response = client.get("/documents/", headers=headers)
        assert response.status_code == 200

        titles = [d["title"] for d in response.json()]
        assert "Employee Handbook" in titles
        assert "Q3 Roadmap" not in titles
        assert "Executive Compensation" not in titles

    def test_manager_sees_viewer_and_manager_tier_but_not_admin(
        self, client, manager_user, seeded_documents
    ):
        headers = self._get_auth_header(manager_user.email, "manager")
        response = client.get("/documents/", headers=headers)
        assert response.status_code == 200

        titles = [d["title"] for d in response.json()]
        assert "Employee Handbook" in titles
        assert "Q3 Roadmap" in titles
        assert "Executive Compensation" not in titles

    def test_admin_sees_all_documents(self, client, admin_user, seeded_documents):
        headers = self._get_auth_header(admin_user.email, "admin")
        response = client.get("/documents/", headers=headers)
        assert response.status_code == 200

        titles = [d["title"] for d in response.json()]
        assert "Employee Handbook" in titles
        assert "Q3 Roadmap" in titles
        assert "Executive Compensation" in titles
