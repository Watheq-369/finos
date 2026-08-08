"""The canonical objects. Every source produces a ContractEvent, every stage fills it in."""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Route(str, Enum):
    INVOICE = "INVOICE"  # signed contract, proceed to draft invoice
    HOLD = "HOLD"  # unsigned proposal, wait
    REJECT = "REJECT"  # not a contract, or a duplicate
    FLAG = "FLAG"  # unsure, escalate to owner


class Source(str, Enum):
    GMAIL = "gmail"
    HUBSPOT = "hubspot"
    FORM = "form"
    STRIPE = "stripe"


class TrustLevel(str, Enum):
    UNTRUSTED = "untrusted"  # email, attacker-reachable
    TRUSTED = "trusted"  # internal CRM deal


class VatTreatment(str, Enum):
    STANDARD = "standard"
    PLUS_VAT = "plus_vat"
    REVERSE_CHARGE = "reverse_charge"
    NONE = "none"
    UNKNOWN = "unknown"


class ScheduleItem(BaseModel):
    portion: str  # "100%", "milestone 1", "50% upfront"
    trigger: Optional[str] = None  # "on signature", "2026-11-01", "on delivery"


class ContractEvent(BaseModel):
    # set by the adapter
    event_id: str  # from source + message id
    source: Source
    trust_level: TrustLevel
    received_at: datetime
    raw_ref: str  # pointer to the stored raw email

    # set by the pipeline
    route: Optional[Route] = None
    client_name: Optional[str] = None
    client_email: Optional[str] = None
    total_amount: Optional[Decimal] = None  # the whole engagement
    invoice_amount: Optional[Decimal] = None  # the part being billed now
    currency: Optional[str] = None  # ISO 4217, e.g. EUR
    vat_treatment: VatTreatment = VatTreatment.UNKNOWN
    vat_rate: Optional[Decimal] = None
    tax_id: Optional[str] = None  # VAT number or TRN
    payment_terms: Optional[str] = None
    schedule: list[ScheduleItem] = Field(default_factory=list)
    confidence: dict[str, float] = Field(default_factory=dict)
    flags: list[str] = Field(default_factory=list)
