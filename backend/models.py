from sqlalchemy import (
    Column, Integer, String, Float, Date, DateTime, ForeignKey, Text
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    monthly_income = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    transactions = relationship(
        "Transaction", back_populates="owner", cascade="all, delete-orphan"
    )
    insights = relationship(
        "Insight", back_populates="owner", cascade="all, delete-orphan"
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    description = Column(String, nullable=False)
    amount = Column(Float, nullable=False)  # positive = expense
    category = Column(String, nullable=False, default="Uncategorized")
    category_source = Column(String, default="manual")  # manual | rule | model | zero_shot
    is_anomaly = Column(Integer, default=0)  # 0/1 flag
    anomaly_score = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    owner = relationship("User", back_populates="transactions")


class Insight(Base):
    __tablename__ = "insights"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    kind = Column(String, nullable=False)  # forecast | persona | budget
    payload = Column(Text, nullable=False)  # JSON blob
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    owner = relationship("User", back_populates="insights")
