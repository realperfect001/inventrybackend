from datetime import datetime
from typing import Optional
from enum import Enum

from sqlmodel import SQLModel, Field


class ScanAction(str, Enum):
    stock_in = "stock_in"
    stock_out = "stock_out"
    unregistered = "unregistered"


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    password_hash: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Goods(SQLModel, table=True):
    """One row per RFID tag. Each tag represents one pack of a good
    (default: a dozen / 12 units)."""
    uid: str = Field(primary_key=True)
    name: str = "Unregistered"
    registered: bool = False   # True once an admin has named this tag from the dashboard
    category: Optional[str] = None
    units_per_pack: int = 12          # how many individual units one tag/pack represents
    quantity: int = 0                  # current stock, in individual units
    low_stock_threshold: int = 24      # alert when quantity drops to/below this
    last_action: Optional[ScanAction] = None
    last_scanned_at: Optional[datetime] = None
    last_station: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ScanLog(SQLModel, table=True):
    """History of every physical tag scan from the ESP32."""
    id: Optional[int] = Field(default=None, primary_key=True)
    uid: str
    action: ScanAction
    quantity_change: int
    resulting_quantity: int
    station_id: Optional[str] = None
    scanned_at: datetime = Field(default_factory=datetime.utcnow)


class AdjustmentLog(SQLModel, table=True):
    """History of manual stock corrections made from the dashboard."""
    id: Optional[int] = Field(default=None, primary_key=True)
    uid: str
    delta: int
    reason: Optional[str] = None
    performed_by: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
