from sqlalchemy.types import String

from website import db
from sqlalchemy.orm import Mapped, mapped_column

# Requirement: (Customer name, address, telephone number, email address, etc.)
class Customer(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    address: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    phone: Mapped[str] = mapped_column(String(15))

    def __repr__(self) -> str:
        return f"[{self.id}] {self.name}"
