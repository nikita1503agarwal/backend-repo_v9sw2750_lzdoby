import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import User, Wallet, Transaction

app = FastAPI(title="Kenya Fintech API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"message": "Kenya Fintech Backend is running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                response["collections"] = db.list_collection_names()[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    return response


# Utility to normalize phone numbers (simple heuristic)
def normalize_phone(phone: str) -> str:
    p = phone.strip().replace(" ", "")
    if p.startswith("+254"):  # already intl format
        return p
    if p.startswith("07") and len(p) == 10:
        return "+254" + p[1:]
    if p.startswith("254") and len(p) == 12:
        return "+" + p
    return p


class RegisterUserRequest(BaseModel):
    name: str
    email: str
    phone: str
    national_id: Optional[str] = None


@app.post("/api/users/register")
def register_user(payload: RegisterUserRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    phone_norm = normalize_phone(payload.phone)

    # Ensure unique phone wallet
    existing = db["wallet"].find_one({"phone": phone_norm})
    if existing:
        raise HTTPException(status_code=400, detail="Phone already registered")

    # Create user
    user = User(
        name=payload.name,
        email=payload.email,
        phone=phone_norm,
        national_id=payload.national_id,
        is_active=True,
    )
    user_id = create_document("user", user)

    # Create wallet with 0 balance
    wallet = Wallet(user_id=user_id, phone=phone_norm, currency="KES", balance=0.0)
    create_document("wallet", wallet)

    return {"status": "ok", "user_id": user_id, "phone": phone_norm}


class TopUpRequest(BaseModel):
    phone: str
    amount: float


@app.post("/api/wallet/topup")
def topup_wallet(payload: TopUpRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    phone_norm = normalize_phone(payload.phone)
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be > 0")

    wal = db["wallet"].find_one({"phone": phone_norm})
    if not wal:
        raise HTTPException(status_code=404, detail="Wallet not found")

    new_balance = float(wal.get("balance", 0)) + float(payload.amount)
    db["wallet"].update_one({"_id": wal["_id"]}, {"$set": {"balance": new_balance, "updated_at": datetime.now(timezone.utc)}})

    tx = Transaction(
        type="topup",
        from_phone=None,
        to_phone=phone_norm,
        amount=payload.amount,
        currency="KES",
        provider="mpesa-sandbox",
        status="success",
        reference=f"TP{int(datetime.now().timestamp())}"
    )
    create_document("transaction", tx)

    return {"status": "ok", "phone": phone_norm, "balance": new_balance}


class TransferRequest(BaseModel):
    from_phone: str
    to_phone: str
    amount: float


@app.post("/api/wallet/transfer")
def transfer(payload: TransferRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    src = normalize_phone(payload.from_phone)
    dst = normalize_phone(payload.to_phone)

    if src == dst:
        raise HTTPException(status_code=400, detail="Cannot transfer to the same phone")
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be > 0")

    w_src = db["wallet"].find_one({"phone": src})
    w_dst = db["wallet"].find_one({"phone": dst})
    if not w_src or not w_dst:
        raise HTTPException(status_code=404, detail="Source or destination wallet not found")

    if float(w_src.get("balance", 0)) < payload.amount:
        raise HTTPException(status_code=400, detail="Insufficient funds")

    # Deduct and add
    db["wallet"].update_one({"_id": w_src["_id"]}, {"$inc": {"balance": -float(payload.amount)}, "$set": {"updated_at": datetime.now(timezone.utc)}})
    db["wallet"].update_one({"_id": w_dst["_id"]}, {"$inc": {"balance": float(payload.amount)}, "$set": {"updated_at": datetime.now(timezone.utc)}})

    tx = Transaction(
        type="transfer",
        from_phone=src,
        to_phone=dst,
        amount=payload.amount,
        currency="KES",
        provider="internal-ledger",
        status="success",
        reference=f"TR{int(datetime.now().timestamp())}"
    )
    create_document("transaction", tx)

    return {"status": "ok", "from": src, "to": dst, "amount": payload.amount}


@app.get("/api/wallet/{phone}")
def get_wallet(phone: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    p = normalize_phone(phone)
    wal = db["wallet"].find_one({"phone": p})
    if not wal:
        raise HTTPException(status_code=404, detail="Wallet not found")
    return {
        "phone": wal["phone"],
        "currency": wal.get("currency", "KES"),
        "balance": float(wal.get("balance", 0)),
    }


@app.get("/api/transactions/{phone}")
def list_transactions(phone: str, limit: int = 20):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    p = normalize_phone(phone)
    txs = db["transaction"].find({"$or": [{"from_phone": p}, {"to_phone": p}]}) \
        .sort("created_at", -1).limit(limit)
    out = []
    for t in txs:
        out.append({
            "type": t.get("type"),
            "from_phone": t.get("from_phone"),
            "to_phone": t.get("to_phone"),
            "amount": float(t.get("amount", 0)),
            "currency": t.get("currency", "KES"),
            "status": t.get("status", "success"),
            "reference": t.get("reference"),
            "created_at": t.get("created_at")
        })
    return out


# Expose schemas for tooling/viewers
@app.get("/schema")
def get_schema():
    return {
        "user": User.model_json_schema(),
        "wallet": Wallet.model_json_schema(),
        "transaction": Transaction.model_json_schema(),
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
