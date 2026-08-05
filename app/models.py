from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Cabin(Base):
    __tablename__ = "cabins"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)

    bookings: Mapped[list["Booking"]] = relationship(back_populates="cabin")


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (UniqueConstraint("external_id", name="uq_booking_external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(120), index=True)

    cabin_id: Mapped[int] = mapped_column(ForeignKey("cabins.id"))
    cabin: Mapped["Cabin"] = relationship(back_populates="bookings")

    guest_name: Mapped[str] = mapped_column(String(200), default="")
    check_in: Mapped[date] = mapped_column(Date)
    check_out: Mapped[date] = mapped_column(Date)
    total_price: Mapped[float] = mapped_column(Float, default=0.0)
    booking_source: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(60), default="")

    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    flags: Mapped[list["StayFlag"]] = relationship(back_populates="booking", cascade="all, delete-orphan")

    @property
    def nights(self) -> int:
        return max((self.check_out - self.check_in).days, 0)


class StayFlag(Base):
    """An issue or occurrence noted against a stay (e.g. damage, complaint, late checkout)."""

    __tablename__ = "stay_flags"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"))
    booking: Mapped["Booking"] = relationship(back_populates="flags")

    category: Mapped[str] = mapped_column(String(60), default="issue")  # issue | damage | complaint | note
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Expense(Base):
    """Manually entered monthly costs (e.g. supplies) not tied to a single stay."""

    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    month: Mapped[date] = mapped_column(Date)  # stored as the 1st of the month
    category: Mapped[str] = mapped_column(String(80), default="supplies")
    description: Mapped[str] = mapped_column(String(300), default="")
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
