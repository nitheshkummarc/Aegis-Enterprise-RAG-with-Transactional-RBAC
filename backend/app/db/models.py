"""SQLAlchemy ORM models for ClearanceRAG.

These map to the schema defined in Section 3 of the Master Build Prompt.
The embedding column uses pgvector's Vector type (not ARRAY(Float)) to
support the <=> cosine distance operator and HNSW index.
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    CheckConstraint,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship
from pgvector.sqlalchemy import Vector


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


class UserRole(str, enum.Enum):
    """Application roles matching the database user_role ENUM."""
    viewer = "viewer"
    manager = "manager"
    admin = "admin"


# Mapping from role name to numeric level for permission comparisons.
# The query uses: WHERE min_role_level <= user_role_level
ROLE_LEVEL_MAP = {
    UserRole.viewer: 0,
    UserRole.manager: 1,
    UserRole.admin: 2,
}


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(Text, unique=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    role = Column(Enum(UserRole, name="user_role", create_type=False), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    documents = relationship("Document", back_populates="uploader")


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(Text, nullable=False)
    uploaded_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    min_role_level = Column(
        SmallInteger,
        CheckConstraint("min_role_level BETWEEN 0 AND 2", name="ck_documents_min_role_level"),
        nullable=False,
    )
    status = Column(
        Text,
        CheckConstraint(
            "status IN ('processing', 'ready', 'failed')",
            name="ck_documents_status",
        ),
        nullable=False,
        default="processing",
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    uploader = relationship("User", back_populates="documents")
    chunks = relationship(
        "DocumentChunk", back_populates="document", cascade="all, delete-orphan"
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_document_chunk_index"),
        CheckConstraint(
            "min_role_level BETWEEN 0 AND 2",
            name="ck_document_chunks_min_role_level",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index = Column(Integer, nullable=False)
    text_content = Column(Text, nullable=False)
    embedding = Column(Vector(1536), nullable=False)
    min_role_level = Column(SmallInteger, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    document = relationship("Document", back_populates="chunks")
