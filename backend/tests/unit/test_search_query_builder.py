"""Unit tests for the search query builder.

Tests: SQL uses parameterized queries (no string interpolation),
correct operator (<=> cosine), correct LIMIT, role level mapping.
"""

import pytest

from app.retrieval.search import (
    PERMISSION_FILTERED_SEARCH_SQL,
    get_role_level,
    permission_filtered_search,
)
from app.db.models import UserRole, ROLE_LEVEL_MAP


class TestRoleLevelMapping:
    """Tests for role → numeric level mapping."""

    def test_viewer_is_level_0(self):
        assert get_role_level(UserRole.viewer) == 0

    def test_manager_is_level_1(self):
        assert get_role_level(UserRole.manager) == 1

    def test_admin_is_level_2(self):
        assert get_role_level(UserRole.admin) == 2

    def test_role_level_map_complete(self):
        """All three roles have entries in the mapping."""
        assert len(ROLE_LEVEL_MAP) == 3
        assert set(ROLE_LEVEL_MAP.keys()) == {
            UserRole.viewer,
            UserRole.manager,
            UserRole.admin,
        }


class TestSearchSQLStructure:
    """Tests that the SQL query is structured correctly."""

    def test_sql_uses_cosine_distance_operator(self):
        """The SQL must use <=> (cosine), NOT <-> (L2)."""
        sql_text = PERMISSION_FILTERED_SEARCH_SQL.text
        assert "<=>" in sql_text, "SQL must use <=> (cosine distance) operator"
        # Ensure it's NOT using L2 distance
        assert "<->" not in sql_text, "SQL must NOT use <-> (L2 distance)"

    def test_sql_uses_parameterized_queries(self):
        """SQL uses :named_params, never string interpolation.

        This is the SQL injection check — role is never interpolated.
        """
        sql_text = PERMISSION_FILTERED_SEARCH_SQL.text
        assert ":user_role_level" in sql_text
        assert ":query_embedding" in sql_text
        assert ":limit" in sql_text
        # Must NOT contain Python format strings
        assert "%s" not in sql_text
        assert "f'" not in sql_text
        assert "f\"" not in sql_text

    def test_sql_has_permission_filter(self):
        """SQL includes the WHERE clause for permission filtering."""
        sql_text = PERMISSION_FILTERED_SEARCH_SQL.text
        assert "min_role_level <= :user_role_level" in sql_text

    def test_sql_has_limit(self):
        """SQL includes LIMIT clause."""
        sql_text = PERMISSION_FILTERED_SEARCH_SQL.text
        assert "LIMIT :limit" in sql_text

    def test_sql_joins_documents_for_title(self):
        """SQL JOINs to documents table to get title."""
        sql_text = PERMISSION_FILTERED_SEARCH_SQL.text
        assert "JOIN documents" in sql_text
        assert "d.title" in sql_text

    def test_sql_orders_by_cosine_distance(self):
        """SQL ORDER BY uses <=> for cosine distance ranking."""
        sql_text = PERMISSION_FILTERED_SEARCH_SQL.text
        assert "ORDER BY" in sql_text
        # The ORDER BY should use the same <=> operator
        lines = [l.strip() for l in sql_text.split("\n")]
        order_line = [l for l in lines if "ORDER BY" in l]
        assert len(order_line) == 1
        assert "<=>" in order_line[0]
