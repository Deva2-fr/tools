from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class SubscriptionIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["domain", "hosting", "saas", "insurance", "contract", "other"] = "saas"
    vendor: str = ""
    cost: float = Field(0, ge=0, lt=100_000_000)
    period: Literal["monthly", "quarterly", "yearly"] = "yearly"
    renewal_date: date | None = None
    notice_days: int = Field(30, ge=0, le=365)
    auto_renew: bool = True
    active: bool = True
    notes: str = ""


class BankAccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    initial_balance: float = 0
    iban: str = ""


class TransactionIn(BaseModel):
    account_id: int
    tx_date: date
    label: str = Field(min_length=1, max_length=300)
    amount: float = Field(lt=1_000_000_000, gt=-1_000_000_000)
    category: str = ""


class TransactionImport(BaseModel):
    account_id: int
    csv: str = Field(max_length=2_000_000)


class TimeEntryIn(BaseModel):
    work_date: date
    hours: float = Field(gt=0, le=24)
    company_id: int | None = None
    project_id: int | None = None
    description: str = ""
    billable: bool = True
    hourly_rate: float | None = Field(None, ge=0, lt=10_000)


class EmployeeIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str = ""
    job_title: str = ""
    contract: str = "CDI"
    start_date: date | None = None
    end_date: date | None = None
    daily_cost: float = Field(0, ge=0, lt=100_000)
    leave_days_per_year: float = Field(25, ge=0, le=366)
    notes: str = ""


class LeaveIn(BaseModel):
    employee_id: int | None = None  # ignoré pour un membre : on utilise son propre profil
    start_date: date
    end_date: date
    kind: Literal["paid", "rtt", "sick", "unpaid"] = "paid"
    note: str = ""

    @model_validator(mode="after")
    def _order(self):
        if self.end_date < self.start_date:
            raise ValueError("La date de fin précède la date de début")
        return self


class LeaveDecision(BaseModel):
    status: Literal["approved", "refused"]


class ChecklistIn(BaseModel):
    employee_id: int
    kind: Literal["onboarding", "offboarding"] = "onboarding"
    title: str = Field(min_length=1, max_length=300)
    done: bool = False


class AccessIn(BaseModel):
    system: str = Field(min_length=1, max_length=200)
    account: str = ""
    secret_location: str = ""
    holders: str = ""
    last_rotated: date | None = None
    rotate_every_days: int = Field(365, ge=0, le=3650)
    notes: str = ""
