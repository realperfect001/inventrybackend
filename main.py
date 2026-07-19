"""
FastAPI Inventory Tracking Backend
----------------------------------
- Login-protected dashboard API (JWT auth, Argon2-hashed passwords)
- Seeds a default admin user on first run: admin / admin123
- Each RFID tag = one "goods" record; dashboard sets its name/category
- Each scan moves one pack (default 12 units / a dozen) in or out of stock
- Manual stock adjustments + full scan/adjustment history

Run:
    pip install -r requirements.txt
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload

First login:
    POST /auth/login (form fields: username=admin, password=admin123)
    -> then call /auth/change-password immediately in production.
"""

from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, Header, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import SQLModel, Session, select

from config import DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD, DEVICE_API_KEY
from database import engine, get_session
from models import User, Goods, ScanLog, AdjustmentLog, ScanAction
from auth import (
    hash_password, verify_password, create_access_token,
    authenticate_user, get_current_user,
)

app = FastAPI(title="RFID Inventory Tracker")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to your dashboard's exact origin in production
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    SQLModel.metadata.create_all(engine)
    # Seed the default admin account only if no users exist yet
    with Session(engine) as session:
        existing_user = session.exec(select(User)).first()
        if not existing_user:
            admin = User(
                username=DEFAULT_ADMIN_USERNAME,
                password_hash=hash_password(DEFAULT_ADMIN_PASSWORD),
            )
            session.add(admin)
            session.commit()
            print(f"Seeded default admin user '{DEFAULT_ADMIN_USERNAME}'. "
                  f"Change this password after first login!")


# ==================== AUTH ====================

@app.post("/auth/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), session: Session = Depends(get_session)):
    user = authenticate_user(session, form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password")
    token = create_access_token({"sub": user.username})
    return {"access_token": token, "token_type": "bearer"}


@app.get("/auth/me")
def read_me(current_user: User = Depends(get_current_user)):
    return {"username": current_user.username, "created_at": current_user.created_at}


class PasswordChange(SQLModel):
    current_password: str
    new_password: str


@app.post("/auth/change-password")
def change_password(
    data: PasswordChange,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if not verify_password(data.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(data.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")

    user = session.get(User, current_user.id)
    user.password_hash = hash_password(data.new_password)
    session.add(user)
    session.commit()
    return {"message": "Password updated successfully"}


# ==================== DEVICE AUTH (protects /scan from randoms) ====================

def verify_device_key(x_api_key: Optional[str] = Header(default=None)):
    if x_api_key != DEVICE_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid device API key")


# ==================== SCHEMAS ====================

class ScanIn(SQLModel):
    uid: str
    station_id: Optional[str] = None


class GoodsRegister(SQLModel):
    uid: str
    name: str
    category: Optional[str] = None
    units_per_pack: int = 12
    low_stock_threshold: int = 24


class GoodsUpdate(SQLModel):
    name: Optional[str] = None
    category: Optional[str] = None
    units_per_pack: Optional[int] = None
    low_stock_threshold: Optional[int] = None


class AdjustIn(SQLModel):
    delta: int             # positive = add stock, negative = remove stock
    reason: Optional[str] = None


# ==================== SCAN (called by the ESP32) ====================

@app.post("/scan", dependencies=[Depends(verify_device_key)])
def receive_scan(scan: ScanIn, session: Session = Depends(get_session)):
    """
    Each scan moves one pack (units_per_pack, default 12) in or out.
    Direction toggles per tag: first-ever scan of a new tag = stock_in.
    """
    goods = session.get(Goods, scan.uid)
    if goods is None:
        goods = Goods(uid=scan.uid)  # stays "Unregistered" until named from the dashboard

    action = (
        ScanAction.stock_out
        if goods.last_action == ScanAction.stock_in
        else ScanAction.stock_in
    )
    change = goods.units_per_pack if action == ScanAction.stock_in else -goods.units_per_pack
    new_quantity = max(0, goods.quantity + change)

    goods.quantity = new_quantity
    goods.last_action = action
    goods.last_scanned_at = datetime.utcnow()
    goods.last_station = scan.station_id
    goods.updated_at = datetime.utcnow()
    session.add(goods)

    log = ScanLog(
        uid=scan.uid,
        action=action,
        quantity_change=change,
        resulting_quantity=new_quantity,
        station_id=scan.station_id,
    )
    session.add(log)
    session.commit()
    session.refresh(goods)

    return {
        "uid": goods.uid,
        "name": goods.name,
        "action": action,
        "quantity": goods.quantity,
        "low_stock": goods.quantity <= goods.low_stock_threshold,
    }


# ==================== GOODS MANAGEMENT (dashboard, login required) ====================

@app.post("/goods", response_model=Goods)
def register_goods(
    data: GoodsRegister,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Name/register a tag as a specific good. Call again on the same uid to rename it."""
    goods = session.get(Goods, data.uid)
    if goods is None:
        goods = Goods(uid=data.uid)
    goods.name = data.name
    goods.category = data.category
    goods.units_per_pack = data.units_per_pack
    goods.low_stock_threshold = data.low_stock_threshold
    goods.updated_at = datetime.utcnow()
    session.add(goods)
    session.commit()
    session.refresh(goods)
    return goods


@app.get("/goods", response_model=List[Goods])
def list_goods(session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    return session.exec(select(Goods)).all()


@app.get("/goods/{uid}", response_model=Goods)
def get_goods(uid: str, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    goods = session.get(Goods, uid)
    if not goods:
        raise HTTPException(status_code=404, detail="Goods not found")
    return goods


@app.put("/goods/{uid}", response_model=Goods)
def update_goods(
    uid: str,
    data: GoodsUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    goods = session.get(Goods, uid)
    if not goods:
        raise HTTPException(status_code=404, detail="Goods not found")
    if data.name is not None:
        goods.name = data.name
    if data.category is not None:
        goods.category = data.category
    if data.units_per_pack is not None:
        goods.units_per_pack = data.units_per_pack
    if data.low_stock_threshold is not None:
        goods.low_stock_threshold = data.low_stock_threshold
    goods.updated_at = datetime.utcnow()
    session.add(goods)
    session.commit()
    session.refresh(goods)
    return goods


@app.delete("/goods/{uid}")
def delete_goods(uid: str, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    goods = session.get(Goods, uid)
    if not goods:
        raise HTTPException(status_code=404, detail="Goods not found")
    session.delete(goods)
    session.commit()
    return {"message": f"Goods '{uid}' deleted"}


@app.post("/goods/{uid}/adjust", response_model=Goods)
def adjust_stock(
    uid: str,
    data: AdjustIn,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Manual stock correction from the dashboard (damaged goods, stocktake fix, etc)."""
    goods = session.get(Goods, uid)
    if not goods:
        raise HTTPException(status_code=404, detail="Goods not found")

    goods.quantity = max(0, goods.quantity + data.delta)
    goods.updated_at = datetime.utcnow()
    session.add(goods)

    log = AdjustmentLog(uid=uid, delta=data.delta, reason=data.reason, performed_by=current_user.username)
    session.add(log)

    session.commit()
    session.refresh(goods)
    return goods


@app.get("/goods/low-stock/list", response_model=List[Goods])
def low_stock_goods(session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    goods = session.exec(select(Goods)).all()
    return [g for g in goods if g.quantity <= g.low_stock_threshold]


# ==================== LOGS ====================

@app.get("/logs", response_model=List[ScanLog])
def get_scan_logs(
    uid: Optional[str] = None,
    limit: int = 50,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    statement = select(ScanLog)
    if uid:
        statement = statement.where(ScanLog.uid == uid)
    statement = statement.order_by(ScanLog.scanned_at.desc()).limit(limit)
    return session.exec(statement).all()


@app.get("/logs/adjustments", response_model=List[AdjustmentLog])
def get_adjustment_logs(
    uid: Optional[str] = None,
    limit: int = 50,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    statement = select(AdjustmentLog)
    if uid:
        statement = statement.where(AdjustmentLog.uid == uid)
    statement = statement.order_by(AdjustmentLog.created_at.desc()).limit(limit)
    return session.exec(statement).all()
