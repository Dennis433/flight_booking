from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView
from flask_admin import AdminIndexView, expose
from flask_mail import Mail, Message
from markupsafe import Markup
from config import Config
from models import db, User, Airport, Flight, Booking, Payment, Notification
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import timedelta, datetime, timezone
import httpx
import os
import re

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)

# ─── Mail ──────────────────────────────────────────────────
app.config['MAIL_SERVER']         = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT']           = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS']        = True
app.config['MAIL_USERNAME']       = os.getenv('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD']       = os.getenv('MAIL_PASSWORD', '')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_USERNAME', 'noreply@skychain.com')

mail = Mail(app)


def send_receipt(booking):
    to = booking.contact_email or (booking.user.email if booking.user else None)
    if not to or not app.config.get('MAIL_USERNAME'):
        return

    flight = booking.flight
    body   = f"""
Hello {booking.user.full_name},

Your SkyChain booking is confirmed!

─────────────────────────────
BOOKING REFERENCE: {booking.id[:8].upper()}
─────────────────────────────
Flight:      {flight.flight_number}
Route:       {flight.origin.iata_code} → {flight.destination.iata_code}
Departure:   {flight.departure_time.strftime('%d %b %Y %H:%M')} UTC
Arrival:     {flight.arrival_time.strftime('%d %b %Y %H:%M')} UTC
Passengers:  {booking.passengers}
Total paid:  ${booking.total_usd:.2f}
─────────────────────────────

Check-in opens 48 hours before departure at:
https://flight-booking-z1gc.onrender.com/checkin/{booking.id}

Thank you for flying with SkyChain.
"""
    try:
        msg = Message(
            subject    = f'SkyChain Booking Confirmed — {booking.id[:8].upper()}',
            recipients = [to],
            body       = body
        )
        mail.send(msg)
    except Exception as e:
        print(f'[mail] Failed to send receipt: {e}')


# ─── Admin Security ────────────────────────────────────────

class SecureAdminIndex(AdminIndexView):
    def is_accessible(self):
        return session.get('is_admin', False)

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for('admin_login'))


class SecureModelView(ModelView):
    def is_accessible(self):
        return session.get('is_admin', False)

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for('admin_login'))


# ─── Custom Admin Views ────────────────────────────────────

class PaymentAdmin(SecureModelView):
    column_list            = ['id', 'booking_id', 'crypto_type', 'amount_crypto', 'tx_hash', 'status', 'created_at', 'actions']
    column_searchable_list = ['tx_hash', 'crypto_type', 'status']
    can_delete             = False
    can_create             = False
    list_template          = 'admin/payment_list.html'

    def _confirm_formatter(view, context, model, name):
        if model.status == 'pending':
            return Markup(
                f'<button onclick="confirmPayment(\'{model.id}\')" '
                f'style="background:#2563EB;color:#fff;border:none;padding:4px 12px;'
                f'border-radius:6px;cursor:pointer;font-size:0.8rem;">Confirm</button>'
            )
        return Markup(f'<span style="color:#4ade80;font-size:0.8rem;">✓ {model.status}</span>')

    column_formatters = {
        'actions': _confirm_formatter
    }

    column_labels = {
        'actions': 'Action'
    }

    @expose('/confirm/<payment_id>', methods=['POST'])
    def confirm_payment(self, payment_id):
        payment                = Payment.query.get_or_404(payment_id)
        payment.status         = 'confirmed'
        payment.confirmed_at   = datetime.now(timezone.utc)
        payment.booking.status = 'confirmed'

        booking = payment.booking
        try:
            notif_body = (
                f'Your flight {booking.flight.flight_number} '
                f'({booking.flight.origin.iata_code} → {booking.flight.destination.iata_code}) '
                f'on {booking.flight.departure_time.strftime("%d %b %Y")} is confirmed. '
                f'Ref: {booking.id[:8].upper()}'
            )
        except Exception:
            notif_body = f'Your booking {booking.id[:8].upper()} has been confirmed.'

        notification = Notification(
            user_id    = booking.user_id,
            booking_id = booking.id,
            type       = 'payment_confirmed',
            title      = 'Booking confirmed ✓',
            body       = notif_body,
            read       = False
        )
        db.session.add(notification)
        db.session.commit()

        send_receipt(booking)
        return ('', 204)


class BookingAdmin(SecureModelView):
    column_list            = ['id', 'user_id', 'flight_id', 'passengers', 'total_usd', 'status', 'contact_email', 'contact_phone', 'checked_in', 'created_at']
    column_searchable_list = ['status', 'id', 'contact_email']
    column_filters         = ['status', 'checked_in']
    can_create             = False


class FlightAdmin(SecureModelView):
    column_list            = ['flight_number', 'origin', 'destination', 'departure_time', 'arrival_time', 'price_usd', 'seats_available', 'cabin_class']
    column_searchable_list = ['flight_number', 'cabin_class']
    form_excluded_columns  = ['bookings']


class UserAdmin(SecureModelView):
    column_list            = ['id', 'full_name', 'email', 'created_at']
    column_searchable_list = ['email', 'full_name']
    can_create             = False
    column_exclude_list    = ['password_hash']
    form_excluded_columns  = ['password_hash', 'bookings']


# ─── Register Admin ────────────────────────────────────────

admin = Admin(
    app,
    name='SkyChain Admin',
    index_view=SecureAdminIndex()
)

admin.add_view(FlightAdmin(Flight,      db, name='Flights'))
admin.add_view(BookingAdmin(Booking,    db, name='Bookings'))
admin.add_view(PaymentAdmin(Payment,    db, name='Payments'))
admin.add_view(UserAdmin(User,          db, name='Users'))
admin.add_view(SecureModelView(Airport, db, name='Airports'))


# ─── Admin Login ───────────────────────────────────────────

ADMIN_EMAIL    = os.getenv('ADMIN_EMAIL', 'admin@skychain.com')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin1234')


@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        data = request.get_json()
        if data.get('email') == ADMIN_EMAIL and data.get('password') == ADMIN_PASSWORD:
            session['is_admin'] = True
            return jsonify({'message': 'ok'}), 200
        return jsonify({'error': 'Invalid credentials'}), 401
    return render_template('admin_login.html')


@app.route('/admin-logout')
def admin_logout():
    session.pop('is_admin', None)
    return redirect(url_for('index'))


# ─── Auth Routes ───────────────────────────────────────────

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        data = request.get_json()
        if User.query.filter_by(email=data['email']).first():
            return jsonify({'error': 'Email already registered'}), 400
        user = User(
            email         = data['email'],
            full_name     = data['full_name'],
            password_hash = generate_password_hash(data['password'])
        )
        db.session.add(user)
        db.session.commit()
        return jsonify({'message': 'Account created'}), 201
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.get_json()
        user = User.query.filter_by(email=data['email']).first()
        if not user or not check_password_hash(user.password_hash, data['password']):
            return jsonify({'error': 'Invalid credentials'}), 401
        session['user_id'] = user.id
        return jsonify({'message': 'Logged in'}), 200
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


# ─── Main Routes ───────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


# ─── Airport Autocomplete ──────────────────────────────────

@app.route('/airports/search')
def airport_search():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])

    results = Airport.query.filter(
        db.or_(
            Airport.iata_code.ilike(f'{q}%'),
            Airport.city.ilike(f'%{q}%'),
            Airport.name.ilike(f'%{q}%'),
            Airport.country.ilike(f'%{q}%')
        )
    ).limit(8).all()

    return jsonify([{
        'iata':    a.iata_code,
        'name':    a.name,
        'city':    a.city,
        'country': a.country,
    } for a in results])


# ─── Flight Search ─────────────────────────────────────────

@app.route('/search')
def search():
    origin      = request.args.get('origin', '').upper()
    destination = request.args.get('destination', '').upper()
    date        = request.args.get('date')

    origin_airport      = Airport.query.filter_by(iata_code=origin).first()
    destination_airport = Airport.query.filter_by(iata_code=destination).first()

    if not origin_airport or not destination_airport:
        return jsonify({'error': 'Invalid airport codes'}), 400

    flights = Flight.query.filter_by(
        origin_id      = origin_airport.id,
        destination_id = destination_airport.id
    ).all()

    results = [{
        'id':            f.id,
        'flight_number': f.flight_number,
        'origin':        f.origin.iata_code,
        'origin_city':   f.origin.city,
        'destination':   f.destination.iata_code,
        'dest_city':     f.destination.city,
        'departure':     f.departure_time.isoformat(),
        'arrival':       f.arrival_time.isoformat(),
        'price_usd':     f.price_usd,
        'seats':         f.seats_available,
        'cabin':         f.cabin_class
    } for f in flights]

    return jsonify(results)


# ─── Extras ────────────────────────────────────────────────

@app.route('/extras/<flight_id>')
def extras(flight_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    flight     = Flight.query.get_or_404(flight_id)
    passengers = request.args.get('passengers', 1)
    return render_template('extras.html', flight=flight, passengers=passengers)


# ─── Passenger Details ─────────────────────────────────────

@app.route('/passengers/<flight_id>', methods=['GET', 'POST'])
def passenger_details(flight_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    flight     = Flight.query.get_or_404(flight_id)
    passengers = int(request.args.get('passengers', 1))

    if request.method == 'POST':
        data        = request.get_json()
        extras_cost = float(data.get('extras_cost', 0))
        total       = (flight.price_usd * passengers) + extras_cost

        booking = Booking(
            user_id          = session['user_id'],
            flight_id        = flight_id,
            passengers       = passengers,
            total_usd        = total,
            checkin_opens_at = flight.departure_time - timedelta(hours=48),
            contact_email    = data.get('contact_email', ''),
            contact_phone    = data.get('contact_phone', '')
        )
        db.session.add(booking)

        if flight.seats_available >= passengers:
            flight.seats_available -= passengers

        db.session.commit()
        return jsonify({'booking_id': booking.id}), 201

    return render_template('passenger_details.html', flight=flight, passengers=passengers)


# ─── Booking Routes ────────────────────────────────────────

@app.route('/book/<flight_id>', methods=['POST'])
def book_flight(flight_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Login required'}), 401

    data       = request.get_json()
    flight     = Flight.query.get_or_404(flight_id)
    passengers = data.get('passengers', 1)

    if flight.seats_available < passengers:
        return jsonify({'error': 'Not enough seats'}), 400

    total = flight.price_usd * passengers

    booking = Booking(
        user_id          = session['user_id'],
        flight_id        = flight_id,
        passengers       = passengers,
        total_usd        = total,
        checkin_opens_at = flight.departure_time - timedelta(hours=48)
    )
    db.session.add(booking)
    db.session.commit()

    return jsonify({'booking_id': booking.id, 'total_usd': total}), 201


# ─── Booking Status ────────────────────────────────────────

@app.route('/booking/<booking_id>/status')
def booking_status(booking_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Login required'}), 401
    booking = Booking.query.get_or_404(booking_id)
    if booking.user_id != session['user_id']:
        return jsonify({'error': 'Unauthorized'}), 403
    payload = {
        'status':         booking.status,
        'payment_status': booking.payment.status if booking.payment else None,
        'booking_id':     booking.id
    }
    if booking.status == 'confirmed':
        payload['confirmation_url'] = url_for('confirmation', booking_id=booking_id)
    return jsonify(payload)


# ─── Payment Routes ────────────────────────────────────────

@app.route('/pay/<booking_id>', methods=['GET'])
def payment_page(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    return render_template('payment.html', booking=booking)


@app.route('/pay/<booking_id>/submit', methods=['POST'])
def submit_payment(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    data    = request.get_json()

    crypto  = data.get('crypto_type', '').upper()
    tx_hash = data.get('tx_hash', '').strip()

    if crypto not in ['BTC', 'ETH', 'SOL']:
        return jsonify({'error': 'Unsupported crypto'}), 400

    if not tx_hash:
        return jsonify({'error': 'Transaction hash is required'}), 400

    # If this booking already has a payment, just redirect — don't create another.
    # Happens when the user hits submit twice or refreshes mid-flight.
    if booking.payment:
        pending_url = url_for('pending_page', booking_id=booking_id)
        return jsonify({
            'message':     'Payment already submitted',
            'payment_id':  booking.payment.id,
            'pending_url': pending_url
        }), 200

    # Reject a tx hash that's already used by any other payment.
    # This catches copy-paste mistakes and protects the unique constraint.
    existing_tx = Payment.query.filter_by(tx_hash=tx_hash).first()
    if existing_tx:
        return jsonify({'error': 'This transaction hash has already been used. Please check your hash and try again.'}), 409

    payment = Payment(
        booking_id    = booking_id,
        crypto_type   = crypto,
        amount_crypto = data.get('amount_crypto'),
        tx_hash       = tx_hash,
        status        = 'pending'
    )
    db.session.add(payment)

    try:
        notif_body = (
            f'We received your {crypto} payment for flight '
            f'{booking.flight.flight_number} '
            f'({booking.flight.origin.iata_code} → {booking.flight.destination.iata_code}). '
            f'Our team is reviewing it and will confirm shortly.'
        )
    except Exception:
        notif_body = f'We received your {crypto} payment for booking {booking.id[:8].upper()}. Confirmation is in progress.'

    notification = Notification(
        user_id    = booking.user_id,
        booking_id = booking_id,
        type       = 'payment_pending',
        title      = 'Payment received — under review',
        body       = notif_body,
        read       = False
    )
    db.session.add(notification)
    db.session.commit()

    pending_url = url_for('pending_page', booking_id=booking_id)
    return jsonify({
        'message':     'Payment submitted, awaiting confirmation',
        'payment_id':  payment.id,
        'pending_url': pending_url
    }), 201


# ─── Pending page ──────────────────────────────────────────

@app.route('/booking/<booking_id>/pending')
def pending_page(booking_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    booking = Booking.query.get_or_404(booking_id)
    if booking.user_id != session['user_id']:
        return 'Unauthorized', 403
    # If already confirmed, skip straight to confirmation
    if booking.status == 'confirmed':
        return redirect(url_for('confirmation', booking_id=booking_id))
    return render_template('pending.html', booking=booking)


# ─── Confirmation ──────────────────────────────────────────

@app.route('/confirmation/<booking_id>')
def confirmation(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    return render_template('confirmation.html', booking=booking)


# ─── Dashboard ─────────────────────────────────────────────

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user     = User.query.get_or_404(session['user_id'])
    bookings = Booking.query.filter_by(
        user_id=user.id
    ).order_by(Booking.created_at.desc()).all()
    return render_template('dashboard.html', user=user, bookings=bookings)


# ─── Cancel Booking ────────────────────────────────────────

@app.route('/booking/<booking_id>/cancel', methods=['POST'])
def cancel_booking(booking_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Login required'}), 401
    booking = Booking.query.get_or_404(booking_id)
    if booking.user_id != session['user_id']:
        return jsonify({'error': 'Unauthorized'}), 403
    booking.status = 'cancelled'
    booking.flight.seats_available += booking.passengers
    db.session.commit()
    return jsonify({'message': 'Booking cancelled'}), 200


# ─── Template Filters ──────────────────────────────────────

@app.template_filter('boardingtime')
def boardingtime_filter(dt):
    boarding = dt - timedelta(minutes=30)
    return boarding.strftime('%H:%M')


# ─── Web Check-in ──────────────────────────────────────────

@app.route('/checkin/<booking_id>', methods=['GET', 'POST'])
def checkin(booking_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    booking = Booking.query.get_or_404(booking_id)

    if booking.user_id != session['user_id']:
        return 'Unauthorized', 403

    if booking.checked_in:
        return redirect(url_for('boarding_pass', booking_id=booking_id))

    if not booking.checkin_available:
        return redirect(url_for('dashboard') + '?checkin_error=' + booking.checkin_status)

    if request.method == 'POST':
        data  = request.get_json()
        seats = data.get('seats', [])

        if not seats or len(seats) != booking.passengers:
            return jsonify({'error': f'Select exactly {booking.passengers} seat(s)'}), 400

        pattern = re.compile(r'^([1-9]|[12]\d|30)[A-F]$')
        for s in seats:
            if not pattern.match(s):
                return jsonify({'error': f'Invalid seat: {s}'}), 400

        taken = {
            b.seat_number
            for b in Booking.query.filter(
                Booking.flight_id  == booking.flight_id,
                Booking.status     == 'confirmed',
                Booking.checked_in == True,
                Booking.id         != booking_id
            ).all()
            if b.seat_number
        }
        taken_individual = set()
        for s in taken:
            taken_individual.update(s.split(','))

        conflicts = [s for s in seats if s in taken_individual]
        if conflicts:
            return jsonify({'error': f'Seat(s) already taken: {", ".join(conflicts)}. Please choose again.'}), 409

        booking.seat_number = ','.join(seats)
        booking.checked_in  = True
        db.session.commit()

        return jsonify({'message': 'Checked in', 'seats': seats}), 200

    taken_seats = set()
    for b in Booking.query.filter(
        Booking.flight_id  == booking.flight_id,
        Booking.status     == 'confirmed',
        Booking.checked_in == True,
        Booking.id         != booking_id
    ).all():
        if b.seat_number:
            taken_seats.update(b.seat_number.split(','))

    return render_template('checkin.html', booking=booking, taken_seats=taken_seats)


# ─── Booking Detail ────────────────────────────────────────

@app.route('/booking/<booking_id>')
def booking_detail(booking_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    booking = Booking.query.get_or_404(booking_id)
    if booking.user_id != session['user_id']:
        return 'Unauthorized', 403
    return render_template('booking_detail.html', booking=booking)


# ─── Boarding Pass ─────────────────────────────────────────

_GATES = ['A1','A2','A3','A4','A5','A6','A7','A8',
          'B1','B2','B3','B4','B5','B6','B7','B8',
          'C1','C2','C3','C4','C10','C11','C12','D1','D2','D3']

def _derive_gate(flight_number: str) -> str:
    seed = sum(ord(c) for c in flight_number)
    return _GATES[seed % len(_GATES)]


@app.route('/boarding-pass/<booking_id>')
def boarding_pass(booking_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    booking = Booking.query.get_or_404(booking_id)

    if booking.user_id != session['user_id']:
        return 'Unauthorized', 403

    if not booking.checked_in:
        return redirect(url_for('checkin', booking_id=booking_id))

    gate = _derive_gate(booking.flight.flight_number)
    return render_template('boarding_pass.html', booking=booking, gate=gate)


# ─── Notification API ──────────────────────────────────────

@app.route('/api/notifications')
def api_notifications():
    if 'user_id' not in session:
        return jsonify([])
    notifications = (
        Notification.query
        .filter_by(user_id=session['user_id'])
        .order_by(Notification.created_at.desc())
        .limit(30)
        .all()
    )
    return jsonify([{
        'id':         n.id,
        'type':       n.type,
        'title':      n.title,
        'body':       n.body,
        'read':       n.read,
        'booking_id': n.booking_id,
        'created_at': n.created_at.strftime('%-d %b, %H:%M') if n.created_at else ''
    } for n in notifications])


@app.route('/api/notifications/unread-count')
def api_notifications_unread_count():
    if 'user_id' not in session:
        return jsonify({'count': 0})
    count = (
        Notification.query
        .filter_by(user_id=session['user_id'], read=False)
        .count()
    )
    return jsonify({'count': count})


@app.route('/api/notifications/read', methods=['POST'])
def api_notifications_mark_read():
    if 'user_id' not in session:
        return jsonify({'error': 'Login required'}), 401
    data           = request.get_json(silent=True) or {}
    notification_id = data.get('id')

    if notification_id:
        # Mark a single notification read
        n = Notification.query.filter_by(
            id=notification_id, user_id=session['user_id']
        ).first()
        if n:
            n.read = True
    else:
        # Mark all as read
        Notification.query.filter_by(
            user_id=session['user_id'], read=False
        ).update({'read': True})

    db.session.commit()
    return jsonify({'ok': True})


# ─── Support Chat (Hard-coded Replies) ────────────────────

# Each entry: (list_of_keywords, reply_string)
# The first rule whose keywords ALL appear in the lowercased user message wins.
_SUPPORT_RULES = [
    # Check-in
    (["check in", "check-in"],
     "Online check-in opens 48 hours before departure and closes 1 hour before. "
     "Head to your dashboard, open the booking, and click Check In — you'll pick your seat "
     "(rows 1-30, seats A-F) and your boarding pass will be ready instantly after."),

    (["boarding pass"],
     "Your boarding pass is available right after you complete online check-in. "
     "Go to your dashboard, open the booking, and tap 'Boarding Pass'. "
     "Check-in opens 48 hrs before departure and closes 1 hr before."),

    (["boarding", "gate", "when to arrive"],
     "Boarding starts 30 minutes before departure — please be at the gate 45 minutes early "
     "so you don't miss your flight."),

    # Payment / crypto
    (["payment", "confirm", "pending", "how long"],
     "After you submit your transaction hash, our team manually reviews it — "
     "this usually takes a few minutes, but can be up to a few hours during busy periods. "
     "You'll get an in-app notification and email the moment it's confirmed. "
     "If it's still pending after 3 hours, email support@skychain.io with your booking "
     "reference and transaction hash."),

    (["crypto", "cryptocurrency", "bitcoin", "ethereum", "solana", "btc", "eth", "sol", "accept"],
     "We accept Bitcoin (BTC), Ethereum (ETH), and Solana (SOL). "
     "Choose your preferred currency at checkout and send the exact amount shown — "
     "then paste your transaction hash to confirm."),

    # Cancellation / changes
    (["cancel", "cancell"],
     "To cancel your booking, email support@skychain.io with your 8-character booking reference. "
     "If you cancel before check-in opens (48 hrs before departure), a refund in the original "
     "crypto may be issued within 3-5 business days after approval. "
     "Cancellations after check-in opens — or no-shows — are non-refundable."),

    (["change", "modify", "reschedule"],
     "To change your booking, contact us at support@skychain.io with your 8-character booking "
     "reference. Changes depend on seat availability and must be requested before check-in opens."),

    # Refund
    (["refund", "money back", "reimburs"],
     "Refunds are possible if you cancel before check-in opens (48 hrs before departure). "
     "Email support@skychain.io with your booking reference — if approved, the refund is returned "
     "in the original crypto within 3-5 business days. Late cancellations and no-shows are non-refundable."),

    # Baggage
    (["baggage", "luggage", "bag", "carry", "suitcase", "kg"],
     "Every passenger gets 1 carry-on bag up to 7 kg for free. "
     "Checked baggage is an optional paid extra you can add during the booking extras step. "
     "For oversized or special items (sports gear, instruments) email support@skychain.io before you fly."),

    # Email / confirmation
    (["confirmation email", "no email", "didn't receive", "did not receive", "email not"],
     "Confirmation emails go out as soon as your payment is confirmed. "
     "Please check your spam/junk folder first — it often ends up there. "
     "All your booking activity is also visible on your dashboard under 'My bookings'."),

    (["email", "notification"],
     "You'll receive an email notification as soon as your payment is confirmed. "
     "All booking details are also available on your dashboard anytime."),

    # Technical issues
    (["not loading", "stuck", "error", "bug", "broken", "technical"],
     "Sorry to hear you're running into an issue! Try clearing your browser cache or switching "
     "to a different browser — that fixes most problems. "
     "If it's still not working, email support@skychain.io and our team will sort it out quickly."),

    # Seat selection
    (["seat", "seat selection", "choose seat"],
     "You pick your seat during online check-in, which opens 48 hours before departure. "
     "We have up to 30 rows with seats A-F available."),

    # Booking reference
    (["booking reference", "reference number", "booking number"],
     "Your 8-character booking reference is shown on your dashboard and on your e-ticket. "
     "You'll need it if you contact us at support@skychain.io for any changes or issues."),

    # Greetings
    (["hello", "hi", "hey", "good morning", "good afternoon", "good evening"],
     "👋 Hi there! I'm the SkyChain support assistant. How can I help you today? "
     "Feel free to ask about payments, check-in, baggage, or anything else."),

    (["thank", "thanks", "thank you"],
     "You're welcome! Is there anything else I can help you with? ✈️"),

    (["bye", "goodbye", "see you"],
     "Safe travels! Feel free to come back if you have any more questions. ✈️"),
]

_FALLBACK_REPLY = (
    "I'm not sure I have a specific answer for that. "
    "For the fastest help, email support@skychain.io with your booking reference "
    "and our team will get back to you promptly."
)


def _hard_coded_reply(user_text: str) -> str:
    """Return the first matching hard-coded reply, or the fallback."""
    lower = user_text.lower()
    for keywords, reply in _SUPPORT_RULES:
        if all(kw in lower for kw in keywords):
            return reply
    return _FALLBACK_REPLY


@app.route('/api/support-chat', methods=['POST'])
def support_chat():
    data     = request.get_json(silent=True) or {}
    messages = data.get('messages', [])
    if not messages:
        return jsonify({'error': 'No messages provided'}), 400

    # Use only the latest user message for matching
    last_user = next(
        (m['content'] for m in reversed(messages) if m.get('role') == 'user'),
        ''
    )
    reply = _hard_coded_reply(last_user)
    return jsonify({'reply': reply})


# ─── Init ──────────────────────────────────────────────────

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
