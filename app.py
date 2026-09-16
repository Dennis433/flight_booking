from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView
from flask_admin import AdminIndexView, expose
from flask_mail import Mail, Message
from markupsafe import Markup
from config import Config
from models import db, User, Airport, Flight, Booking, Payment
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import timedelta, datetime
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
    list_template          = 'admin/payment_confirm.html'

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
        payment.confirmed_at   = datetime.utcnow()
        payment.booking.status = 'confirmed'
        db.session.commit()
        send_receipt(payment.booking)
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
        'departure':     f.departure_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'arrival':       f.arrival_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
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
        extras_cost = float(request.args.get('extras_cost', 0))
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

    return jsonify({'booking_id': None, 'flight_id': flight_id, 'passengers': passengers}), 200


# ─── Booking Status ────────────────────────────────────────

@app.route('/booking/<booking_id>/status')
def booking_status(booking_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Login required'}), 401
    booking = Booking.query.get_or_404(booking_id)
    if booking.user_id != session['user_id']:
        return jsonify({'error': 'Unauthorized'}), 403
    return jsonify({
        'status':         booking.status,
        'payment_status': booking.payment.status if booking.payment else None,
        'booking_id':     booking.id
    })


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
    tx_hash = data.get('tx_hash')

    if crypto not in ['BTC', 'ETH', 'SOL']:
        return jsonify({'error': 'Unsupported crypto'}), 400

    payment = Payment(
        booking_id    = booking_id,
        crypto_type   = crypto,
        amount_crypto = data.get('amount_crypto'),
        tx_hash       = tx_hash,
        status        = 'pending'
    )
    db.session.add(payment)
    db.session.commit()

    return jsonify({
        'message':     'Payment submitted, awaiting confirmation',
        'payment_id':  payment.id,
        'pending_url': f'/booking/{booking_id}/pending'
    }), 201


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


# ─── Support ───────────────────────────────────────────────

@app.route('/support')
def support():
    return render_template('support.html')


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


# ─── Pending ───────────────────────────────────────────────

@app.route('/booking/<booking_id>/pending')
def booking_pending(booking_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    booking = Booking.query.get_or_404(booking_id)
    if booking.user_id != session['user_id']:
        return 'Unauthorized', 403
    return render_template('pending.html', booking=booking)


# ─── Init ──────────────────────────────────────────────────

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
