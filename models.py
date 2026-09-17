from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta, timezone
import uuid

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = 'users'

    id            = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email         = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name     = db.Column(db.String(100), nullable=False)
    created_at    = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    bookings = db.relationship('Booking', backref='user', lazy=True)


class Airport(db.Model):
    __tablename__ = 'airports'

    id        = db.Column(db.Integer, primary_key=True)
    iata_code = db.Column(db.String(3), unique=True, nullable=False)
    name      = db.Column(db.String(200), nullable=False)
    city      = db.Column(db.String(100), nullable=False)
    country   = db.Column(db.String(100), nullable=False)
    latitude  = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)


class Flight(db.Model):
    __tablename__ = 'flights'

    id              = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    flight_number   = db.Column(db.String(10), nullable=False)
    origin_id       = db.Column(db.Integer, db.ForeignKey('airports.id'), nullable=False)
    destination_id  = db.Column(db.Integer, db.ForeignKey('airports.id'), nullable=False)
    departure_time  = db.Column(db.DateTime, nullable=False)
    arrival_time    = db.Column(db.DateTime, nullable=False)
    price_usd       = db.Column(db.Float, nullable=False)
    seats_available = db.Column(db.Integer, default=150)
    cabin_class     = db.Column(db.String(20), default='economy')

    origin      = db.relationship('Airport', foreign_keys=[origin_id])
    destination = db.relationship('Airport', foreign_keys=[destination_id])
    bookings    = db.relationship('Booking', backref='flight', lazy=True)


class Booking(db.Model):
    __tablename__ = 'bookings'

    id         = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id    = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    flight_id  = db.Column(db.String(36), db.ForeignKey('flights.id'), nullable=False)
    passengers = db.Column(db.Integer, default=1)
    total_usd  = db.Column(db.Float, nullable=False)
    status     = db.Column(db.String(20), default='pending')  # pending, confirmed, cancelled
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # ── Contact details (collected at passenger details step) ─────────────────
    # Stored on the booking so confirmation emails and admin views have them
    # without joining to a separate passengers table.
    contact_email = db.Column(db.String(120), nullable=True, default=None)
    contact_phone = db.Column(db.String(30),  nullable=True, default=None)

    # ── Check-in fields ───────────────────────────────────────────────────────
    # seat_number:      assigned at check-in (e.g. "24A"). Null until checked in.
    # checked_in:       True once the passenger has completed web check-in.
    # checkin_opens_at: computed on booking creation — 48 hrs before departure.
    #                   Stored so queries can filter without joining Flight each time.
    seat_number      = db.Column(db.String(10), nullable=True,  default=None)
    checked_in       = db.Column(db.Boolean,    nullable=False, default=False)
    checkin_opens_at = db.Column(db.DateTime,   nullable=True,  default=None)

    payment = db.relationship('Payment', backref='booking', uselist=False)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _as_utc(dt):
        """
        Normalise a datetime to UTC-aware.
        Handles both naive datetimes (old rows stored without tzinfo, assumed UTC)
        and aware datetimes (PostgreSQL timestamptz). Prevents the TypeError:
        can't compare offset-naive and offset-aware datetimes.
        """
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    @property
    def checkin_available(self):
        """True when the check-in window is open and the booking is confirmed."""
        if self.status != 'confirmed' or self.checked_in:
            return False
        now    = datetime.now(timezone.utc)
        opens  = self._as_utc(self.checkin_opens_at)
        closes = self._as_utc(self.flight.departure_time)
        return opens is not None and opens <= now < closes

    @property
    def checkin_status(self):
        """
        Human-readable check-in state. Used in templates and the dashboard.

        Returns one of:
          'checked_in'  — already done
          'open'        — window is open, action available
          'not_yet'     — too early (> 48 hrs before departure)
          'closed'      — past departure
          'unavailable' — booking not confirmed
        """
        if self.checked_in:
            return 'checked_in'
        if self.status != 'confirmed':
            return 'unavailable'
        now       = datetime.now(timezone.utc)
        departure = self._as_utc(self.flight.departure_time)
        opens_at  = self._as_utc(self.checkin_opens_at)
        if now >= departure:
            return 'closed'
        if opens_at and now >= opens_at:
            return 'open'
        return 'not_yet' 


class Payment(db.Model):
    __tablename__ = 'payments'

    id            = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    booking_id    = db.Column(db.String(36), db.ForeignKey('bookings.id'), nullable=False)
    crypto_type   = db.Column(db.String(10), nullable=False)   # BTC, ETH, SOL, USDT, USDC
    chain         = db.Column(db.String(10), nullable=True)    # ETH or SOL — for USDT/USDC
    amount_crypto = db.Column(db.Float, nullable=False)
    tx_hash       = db.Column(db.String(200), unique=True, nullable=True)
    status        = db.Column(db.String(20), default='pending')  # pending, confirmed, failed
    created_at    = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    confirmed_at  = db.Column(db.DateTime, nullable=True)

class Notification(db.Model):
    __tablename__ = 'notifications'

    id         = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id    = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    booking_id = db.Column(db.String(36), db.ForeignKey('bookings.id'), nullable=True)
    type       = db.Column(db.String(30), nullable=False)   # payment_pending | payment_confirmed
    title      = db.Column(db.String(120), nullable=False)
    body       = db.Column(db.Text, nullable=False)
    read       = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user    = db.relationship('User',    foreign_keys=[user_id])
    booking = db.relationship('Booking', foreign_keys=[booking_id])
