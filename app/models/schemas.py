from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


# ── Products ────────────────────────────────────────────────────

class Milestone(BaseModel):
    milestone_n: int
    label: str
    pct: float


class ProductBase(BaseModel):
    code: str
    name: str
    full_name: Optional[str] = None
    description: Optional[str] = None
    base_price: Optional[float] = None         # None = "a cotizar"
    discount_pct: float = 0
    badge_label: Optional[str] = None
    badge_type: Optional[str] = None           # std | prem | custom
    is_active: bool = True
    sort_order: int = 0
    milestones: List[Milestone] = []


class ProductCreate(ProductBase):
    pass


class ProductOut(ProductBase):
    id: str


# ── Client ──────────────────────────────────────────────────────

class ClientData(BaseModel):
    full_name: str = Field(..., min_length=2)
    company: Optional[str] = None
    email: EmailStr
    phone: Optional[str] = None
    country: Optional[str] = None
    jurisdiction: Optional[str] = None


# ── Engagement ──────────────────────────────────────────────────

class PaymentMode(str, Enum):
    hitos = "hitos"
    anticipado = "anticipado"


class SignatureType(str, Enum):
    canvas = "canvas"
    typed = "typed"


class PaymentFieldDetail(BaseModel):
    label: str
    value: str


class PaymentDetails(BaseModel):
    """Método/medio de pago elegido por el cliente (para el PDF y el registro)."""
    method_key: Optional[str] = None
    method_label: Optional[str] = None
    currency: Optional[str] = None
    # Cripto:
    token: Optional[str] = None
    network: Optional[str] = None
    address: Optional[str] = None
    # Fiat: campos de la transferencia (Alias, CVU, IBAN…).
    fields: Optional[List[PaymentFieldDetail]] = None


class EngagementCreate(BaseModel):
    client: ClientData
    product_code: str
    payment_mode: PaymentMode
    custom_description: Optional[str] = None       # For CUSTOM product
    agreed_price: Optional[float] = None           # Manual amount (CUSTOM or override)
    discount_code: Optional[str] = None            # Optional discount code
    signature_type: SignatureType
    signature_data: str                            # base64 PNG
    payment_details: Optional[PaymentDetails] = None   # método/medio elegido
    lang: str = "en"                                   # idioma para PDF/email
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


class EngagementStatus(str, Enum):
    pending = "pending"
    signed = "signed"
    active = "active"
    completed = "completed"
    cancelled = "cancelled"


class EngagementOut(BaseModel):
    id: str
    client_email: str
    client_name: str
    product_code: str
    payment_mode: str
    final_price: Optional[float]
    status: str
    signed_at: Optional[datetime]
    created_at: datetime


# ── Payments ────────────────────────────────────────────────────

class PaymentMethod(str, Enum):
    bank_transfer = "bank_transfer"
    usdt = "usdt"
    btc = "btc"
    eth = "eth"
    other = "other"


class PaymentStatus(str, Enum):
    pending = "pending"
    received = "received"
    verified = "verified"
    rejected = "rejected"


class PaymentUpdate(BaseModel):
    status: PaymentStatus
    verified_by: Optional[str] = None
    notes: Optional[str] = None
