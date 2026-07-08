from datetime import date
from typing import Optional, List
from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    username: str
    password: str
    monthly_income: float = 0.0


class UserLogin(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


class TransactionCreate(BaseModel):
    date: date
    description: str
    amount: float = Field(gt=0)
    category: Optional[str] = None


class TransactionOut(BaseModel):
    id: int
    date: date
    description: str
    amount: float
    category: str
    category_source: str
    is_anomaly: int
    anomaly_score: float

    class Config:
        from_attributes = True


class NLQuery(BaseModel):
    question: str


class CategoryOverride(BaseModel):
    category: str
