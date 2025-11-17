"""
Database Schemas for Fintech (Kenya)

Define MongoDB collection schemas using Pydantic models.
Each Pydantic model corresponds to a collection with the lowercase class name.
- User -> "user"
- Wallet -> "wallet"
- Transaction -> "transaction"
"""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, Literal
from datetime import datetime


class User(BaseModel):
    """
    User profile
    Collection: "user"
    """
    name: str = Field(..., description="Full name")
    email: EmailStr = Field(..., description="Email address")
    phone: str = Field(..., description="Kenyan phone number in +2547XXXXXXXX or 07XXXXXXXX format")
    national_id: Optional[str] = Field(None, description="Optional national ID for KYC")
    is_active: bool = Field(True, description="Whether user is active")


class Wallet(BaseModel):
    """
    Mobile money wallet
    Collection: "wallet"
    """
    user_id: str = Field(..., description="User ObjectId as string")
    phone: str = Field(..., description="Phone linked to wallet")
    currency: Literal['KES'] = Field('KES', description="Currency code")
    balance: float = Field(0.0, ge=0, description="Current balance")


class Transaction(BaseModel):
    """
    Ledger of money movement
    Collection: "transaction"
    """
    type: Literal['topup', 'transfer'] = Field(..., description="Transaction type")
    from_phone: Optional[str] = Field(None, description="Source phone (for transfer)")
    to_phone: Optional[str] = Field(None, description="Destination phone")
    amount: float = Field(..., gt=0, description="Amount in KES")
    currency: Literal['KES'] = Field('KES', description="Currency code")
    provider: Optional[str] = Field(None, description="Provider e.g., mpesa-sandbox")
    status: Literal['success', 'failed', 'pending'] = Field('success', description="Transaction status")
    reference: Optional[str] = Field(None, description="Reference code")
    created_at: Optional[datetime] = Field(default=None, description="Timestamp of creation")
