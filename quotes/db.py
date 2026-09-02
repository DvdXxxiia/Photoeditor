"""PostgreSQL-ready quote store. SQLite is the local default."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker, Session

from quotes.catalog import CATEGORIES, EQUIPMENT, VENDORS


class Base(DeclarativeBase):
    pass


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    function: Mapped[str] = mapped_column(String(80))


class Vendor(Base):
    __tablename__ = "vendors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    quotes: Mapped[list["Quote"]] = relationship(back_populates="vendor")


class Equipment(Base):
    __tablename__ = "equipment"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    brand: Mapped[str] = mapped_column(String(80))
    category: Mapped[str] = mapped_column(String(80))
    function: Mapped[str] = mapped_column(String(80))
    size: Mapped[float | None] = mapped_column(Float, nullable=True)
    aliases: Mapped[str] = mapped_column(Text, default="")
    items: Mapped[list["LineItem"]] = relationship(back_populates="equipment")


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    quotes: Mapped[list["Quote"]] = relationship(back_populates="project")
    comparisons: Mapped[list["Comparison"]] = relationship(back_populates="project")


class Quote(Base):
    __tablename__ = "quotes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    vendor_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id"), nullable=True)
    quote_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    quote_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    filename: Mapped[str] = mapped_column(String(255))
    total: Mapped[float] = mapped_column(Float, default=0)
    raw_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    project: Mapped[Project | None] = relationship(back_populates="quotes")
    vendor: Mapped[Vendor | None] = relationship(back_populates="quotes")
    items: Mapped[list["LineItem"]] = relationship(back_populates="quote", cascade="all, delete-orphan")


class LineItem(Base):
    __tablename__ = "line_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quote_id: Mapped[int] = mapped_column(ForeignKey("quotes.id"))
    equipment_id: Mapped[int | None] = mapped_column(ForeignKey("equipment.id"), nullable=True)
    description: Mapped[str] = mapped_column(String(400))
    sku: Mapped[str | None] = mapped_column(String(80), nullable=True)
    qty: Mapped[float] = mapped_column(Float, default=1)
    unit: Mapped[str] = mapped_column(String(20), default="ea")
    unit_price: Mapped[float] = mapped_column(Float, default=0)
    ext_price: Mapped[float] = mapped_column(Float, default=0)
    function: Mapped[str | None] = mapped_column(String(80), nullable=True)
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    quote: Mapped[Quote] = relationship(back_populates="items")
    equipment: Mapped[Equipment | None] = relationship(back_populates="items")


class Comparison(Base):
    __tablename__ = "comparisons"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    quote_a_id: Mapped[int] = mapped_column(ForeignKey("quotes.id"))
    quote_b_id: Mapped[int] = mapped_column(ForeignKey("quotes.id"))
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    project: Mapped[Project | None] = relationship(back_populates="comparisons")


_engine = None
_SessionLocal = None


def database_url() -> str:
    return os.environ.get("DATABASE_URL", "sqlite:///./quotes.db")


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        url = database_url()
        kwargs = {}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        _engine = create_engine(url, **kwargs)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
        Base.metadata.create_all(_engine)
        _seed(_SessionLocal())
    return _engine


def session() -> Session:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal()


def reset_engine() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def _seed(db: Session) -> None:
    try:
        if db.scalar(select(Vendor.id).limit(1)) is None:
            for name in VENDORS:
                db.add(Vendor(name=name))
        if db.scalar(select(Category.id).limit(1)) is None:
            for name, function in CATEGORIES:
                db.add(Category(name=name, function=function))
        if db.scalar(select(Equipment.id).limit(1)) is None:
            for spec in EQUIPMENT:
                db.add(
                    Equipment(
                        sku=spec.sku,
                        name=spec.name,
                        brand=spec.brand,
                        category=spec.category,
                        function=spec.function,
                        size=spec.size,
                        aliases=",".join(spec.aliases),
                    )
                )
        db.commit()
    finally:
        db.close()
