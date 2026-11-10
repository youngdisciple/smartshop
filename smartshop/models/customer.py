from sqlalchemy.types import String

from smartshop.extensions import db
from sqlalchemy.orm import Mapped, mapped_column
from uuid import uuid4

# Requirements: (Customer email, password, name, address, telephone number)
class Customer(db.Model):
    __table_args__ = (db.CheckConstraint('points >= 0'),)
    email: Mapped[str] = mapped_column(String(50), primary_key=True)
    password: Mapped[str] = mapped_column(String(225), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    address: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(15))
    membership_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, default=lambda: uuid4().hex.upper())
    points: Mapped[int] = mapped_column(nullable=False, default=0)
    is_admin: Mapped[bool] = mapped_column(nullable=False, default=False)

    def __init__(self, email, password, name, address , phone):
        self.email = email
        self.password = password
        self.name = name
        self.address = address
        self.phone = phone

    def __repr__(self) -> str:
        return f"[{self.name}] {self.email}"
