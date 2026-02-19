"""
Authentication Routes for Umuve Backend
Handles phone verification, email login, and Apple Sign In
"""

from flask import Blueprint, request, jsonify
import secrets
import hashlib
import jwt
import datetime
from functools import wraps
import requests
from typing import Optional, Dict

from models import db, User, Referral, generate_referral_code
from extensions import limiter

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

# In-memory storage for demo (use Redis in production)
verification_codes = {}  # phone_number: {code, expires_at}
users_db = {}  # user_id: {id, name, email, phone, password_hash}

# JWT secret — read from env (shared with app_config.Config.JWT_SECRET)
import os
import logging as _logging
_auth_logger = _logging.getLogger(__name__)

JWT_SECRET = os.environ.get('JWT_SECRET', '')
if not JWT_SECRET:
    # Generate a random secret for development; will rotate on restart
    import secrets as _s
    JWT_SECRET = 'dev-only-' + _s.token_hex(32)
    if os.environ.get('FLASK_ENV', 'development') != 'development':
        _auth_logger.warning("JWT_SECRET is not set! Using a random value that will not survive restarts.")

# Apple public keys cache (expires after 24 hours)
_apple_keys_cache = {
    'keys': None,
    'fetched_at': None
}

# MARK: - Helper Functions

def get_apple_public_keys() -> Optional[Dict]:
    """Fetch Apple's public keys for JWT verification (cached for 24 hours)"""
    now = datetime.datetime.utcnow()

    # Check cache
    if _apple_keys_cache['keys'] and _apple_keys_cache['fetched_at']:
        age = (now - _apple_keys_cache['fetched_at']).total_seconds()
        if age < 86400:  # 24 hours
            return _apple_keys_cache['keys']

    # Fetch from Apple
    try:
        response = requests.get('https://appleid.apple.com/auth/keys', timeout=5)
        if response.status_code == 200:
            keys = response.json()
            _apple_keys_cache['keys'] = keys
            _apple_keys_cache['fetched_at'] = now
            return keys
    except Exception as e:
        _auth_logger.error(f"Failed to fetch Apple public keys: {e}")

    return None

def validate_apple_identity_token(identity_token: str, nonce: str) -> Optional[Dict]:
    """Validate Apple identity token JWT and nonce"""
    try:
        # Decode header to get kid
        unverified_header = jwt.get_unverified_header(identity_token)
        kid = unverified_header.get('kid')

        if not kid:
            _auth_logger.error("No kid in Apple identity token")
            return None

        # Get Apple's public keys
        keys_response = get_apple_public_keys()
        if not keys_response:
            _auth_logger.error("Could not fetch Apple public keys")
            return None

        # Find matching key
        public_key = None
        for key in keys_response.get('keys', []):
            if key.get('kid') == kid:
                public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)
                break

        if not public_key:
            _auth_logger.error(f"No matching Apple public key for kid: {kid}")
            return None

        # Verify JWT signature and claims
        payload = jwt.decode(
            identity_token,
            public_key,
            algorithms=['RS256'],
            audience=['com.goumuve.app', 'com.goumuve.pro'],
            issuer='https://appleid.apple.com'
        )

        # Verify nonce
        token_nonce = payload.get('nonce')
        if not token_nonce:
            _auth_logger.error("No nonce in Apple identity token")
            return None

        # Hash the provided nonce and compare
        expected_nonce = hashlib.sha256(nonce.encode()).hexdigest()
        if token_nonce != expected_nonce:
            _auth_logger.error("Nonce mismatch in Apple identity token")
            return None

        return payload

    except jwt.ExpiredSignatureError:
        _auth_logger.error("Apple identity token expired")
        return None
    except jwt.InvalidTokenError as e:
        _auth_logger.error(f"Invalid Apple identity token: {e}")
        return None
    except Exception as e:
        _auth_logger.error(f"Error validating Apple identity token: {e}")
        return None

def generate_verification_code():
    """Generate random 6-digit verification code"""
    return str(secrets.randbelow(900000) + 100000)

def hash_password(password):
    """Simple password hashing (use bcrypt in production)"""
    return hashlib.sha256(password.encode()).hexdigest()

def generate_token(user_id):
    """Generate JWT token for user"""
    payload = {
        'user_id': user_id,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(days=30)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm='HS256')

def verify_token(token):
    """Verify JWT token and return user_id"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
        return payload.get('user_id')
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def require_auth(f):
    """Decorator to require authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        user_id = verify_token(token)
        if not user_id:
            return jsonify({'error': 'Unauthorized'}), 401
        # Verify user exists in either in-memory or SQLAlchemy store
        if user_id not in users_db and not db.session.get(User, user_id):
            return jsonify({'error': 'Unauthorized'}), 401
        return f(user_id=user_id, *args, **kwargs)
    return decorated_function


def optional_auth(f):
    """Decorator that passes user_id if authenticated, None otherwise."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        user_id = verify_token(token) if token else None
        if user_id:
            if user_id not in users_db and not db.session.get(User, user_id):
                user_id = None
        return f(user_id=user_id, *args, **kwargs)
    return decorated_function

# MARK: - Phone Authentication Routes

@auth_bp.route('/send-code', methods=['POST'])
def send_verification_code():
    """Send SMS verification code to phone number"""
    data = request.get_json()
    phone_number = data.get('phoneNumber')
    
    if not phone_number:
        return jsonify({'error': 'Phone number required'}), 400
    
    # Generate and store code
    code = generate_verification_code()
    expires_at = datetime.datetime.utcnow() + datetime.timedelta(minutes=10)
    
    verification_codes[phone_number] = {
        'code': code,
        'expires_at': expires_at
    }
    
    # Send SMS via Twilio (falls back to console print in dev mode)
    from notifications import send_verification_sms
    send_verification_sms(phone_number, code)

    response_data = {
        'success': True,
        'message': 'Verification code sent',
    }
    # Include code in response only when Twilio is not configured (dev mode)
    import os
    if not os.environ.get("TWILIO_ACCOUNT_SID"):
        response_data['code'] = code

    return jsonify(response_data)

@auth_bp.route('/verify-code', methods=['POST'])
def verify_code():
    """Verify SMS code and create/login user"""
    data = request.get_json()
    phone_number = data.get('phoneNumber')
    code = data.get('code')
    
    if not phone_number or not code:
        return jsonify({'error': 'Phone number and code required'}), 400
    
    # Check if code exists
    if phone_number not in verification_codes:
        return jsonify({'error': 'No verification code found'}), 400
    
    stored_data = verification_codes[phone_number]
    
    # Check if code matches
    if stored_data['code'] != code:
        return jsonify({'error': 'Invalid verification code'}), 401
    
    # Check if code expired
    if datetime.datetime.utcnow() > stored_data['expires_at']:
        del verification_codes[phone_number]
        return jsonify({'error': 'Verification code expired'}), 401
    
    # Code is valid - create or get user
    user_id = find_or_create_user_by_phone(phone_number)
    user = users_db[user_id]
    
    # Clear verification code
    del verification_codes[phone_number]
    
    # Generate token
    token = generate_token(user_id)
    
    return jsonify({
        'success': True,
        'token': token,
        'user': {
            'id': user['id'],
            'name': user.get('name'),
            'email': user.get('email'),
            'phoneNumber': user['phoneNumber']
        }
    })

# MARK: - Email Authentication Routes

@auth_bp.route('/signup', methods=['POST'])
@limiter.limit("3 per minute")
def signup():
    """Create new user account with email/password"""
    from werkzeug.security import generate_password_hash
    data = request.get_json(force=True)
    email = data.get('email')
    password = data.get('password')
    name = data.get('name')
    first_name = data.get('first_name', '')
    last_name = data.get('last_name', '')
    if not name and (first_name or last_name):
        name = f"{first_name} {last_name}".strip()

    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400

    # Check if email already exists in DB
    existing = User.query.filter_by(email=email).first()
    if existing:
        return jsonify({'error': 'Email already registered'}), 409

    # Extract optional referral code
    referral_code_input = data.get('referral_code', '').strip().upper() or None

    # Generate a unique referral code for the new user
    new_user_referral_code = None
    for _ in range(10):
        candidate = generate_referral_code()
        if not User.query.filter_by(referral_code=candidate).first():
            new_user_referral_code = candidate
            break

    # Create user in database
    new_user = User(
        email=email,
        name=name,
        password_hash=generate_password_hash(password),
        role='customer',
        referral_code=new_user_referral_code,
    )
    db.session.add(new_user)
    db.session.flush()  # flush to get new_user.id before creating referral

    # If a valid referral code was provided, link the referral
    if referral_code_input:
        referrer = User.query.filter_by(referral_code=referral_code_input).first()
        if referrer and referrer.id != new_user.id:
            referral = Referral(
                referrer_id=referrer.id,
                referee_id=new_user.id,
                referral_code=referral_code_input,
                status='signed_up',
            )
            db.session.add(referral)

    db.session.commit()

    # --- Send welcome email ---
    try:
        from notifications import send_welcome_email
        if new_user.email:
            send_welcome_email(new_user.email, new_user.name)
    except Exception:
        pass  # Notifications must never block the main flow

    # Generate token
    token = generate_token(new_user.id)

    return jsonify({
        'success': True,
        'token': token,
        'user': {
            'id': new_user.id,
            'name': new_user.name,
            'email': new_user.email,
            'phoneNumber': new_user.phone,
            'referral_code': new_user.referral_code
        }
    })

@auth_bp.route('/login', methods=['POST'])
@limiter.limit("5 per minute")
def login():
    """Login with email and password"""
    data = request.get_json(force=True)
    email = data.get('email')
    password = data.get('password')

    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400

    # Check database
    db_user = User.query.filter_by(email=email).first()
    if not db_user or not db_user.check_password(password):
        return jsonify({'error': 'Invalid email or password'}), 401

    token = generate_token(db_user.id)
    return jsonify({
        'success': True,
        'token': token,
        'user': {
            'id': db_user.id,
            'name': db_user.name,
            'email': db_user.email,
            'phoneNumber': db_user.phone,
            'role': db_user.role
        }
    })

# MARK: - Apple Sign In

@auth_bp.route('/apple', methods=['POST'])
def apple_signin():
    """Authenticate with Apple Sign In credential"""
    data = request.get_json()
    identity_token = data.get('identity_token')
    nonce = data.get('nonce')
    user_identifier = data.get('userIdentifier')
    email = data.get('email')
    name = data.get('name')

    # New flow: validate identity_token and nonce
    if identity_token and nonce:
        payload = validate_apple_identity_token(identity_token, nonce)
        if not payload:
            return jsonify({'error': 'Invalid Apple Sign In token'}), 401

        # Extract user identifier from verified token
        user_identifier = payload.get('sub')
        if not user_identifier:
            return jsonify({'error': 'Invalid Apple token payload'}), 400

    # Backward compatibility: fall back to userIdentifier-based flow
    elif user_identifier:
        _auth_logger.warning("Apple Sign In using legacy userIdentifier flow (no token validation)")
    else:
        return jsonify({'error': 'Apple user identifier or identity_token required'}), 400

    # Find or create user
    user = None
    user_id = None

    # Search by Apple ID
    for uid, u in users_db.items():
        if u.get('apple_id') == user_identifier:
            user = u
            user_id = uid
            break

    # Create new user if not found
    if not user:
        user_id = secrets.token_hex(16)
        users_db[user_id] = {
            'id': user_id,
            'apple_id': user_identifier,
            'email': email,
            'name': name,
            'phoneNumber': None
        }
        user = users_db[user_id]

    # Generate token
    token = generate_token(user_id)

    return jsonify({
        'success': True,
        'token': token,
        'user': {
            'id': user['id'],
            'name': user.get('name'),
            'email': user.get('email'),
            'phoneNumber': user.get('phoneNumber')
        }
    })

# MARK: - Forgot Password

@auth_bp.route('/forgot-password', methods=['POST'])
@limiter.limit("3 per minute")
def forgot_password():
    """Request a password reset link"""
    data = request.get_json()
    email = data.get('email')

    if not email:
        return jsonify({'error': 'Email is required'}), 400

    # Check if user exists in database
    db_user = User.query.filter_by(email=email).first()
    if not db_user:
        # Also check in-memory store
        found = any(u.get('email') == email for u in users_db.values())
        if not found:
            return jsonify({'error': 'No account found with that email'}), 404

    # Generate reset token and send via email
    reset_token = secrets.token_urlsafe(32)
    from notifications import send_password_reset_email
    send_password_reset_email(email, reset_token)

    return jsonify({
        'success': True,
        'message': 'Password reset link sent to your email'
    })


# MARK: - Customer Bookings

@auth_bp.route('/me', methods=['GET'])
@require_auth
def get_current_user(user_id):
    """Get current authenticated user profile"""
    # Check database first
    db_user = db.session.get(User, user_id)
    if db_user:
        return jsonify({
            'success': True,
            'user': db_user.to_dict()
        })

    # Check in-memory store
    if user_id in users_db:
        user = users_db[user_id]
        return jsonify({
            'success': True,
            'user': {
                'id': user['id'],
                'name': user.get('name'),
                'email': user.get('email'),
                'phoneNumber': user.get('phoneNumber'),
                'role': 'customer'
            }
        })

    return jsonify({'error': 'User not found'}), 404


@auth_bp.route('/me', methods=['PUT'])
@require_auth
def update_profile(user_id):
    """Update current user profile (name, email, phone)"""
    db_user = db.session.get(User, user_id)
    if not db_user:
        return jsonify({'error': 'User not found'}), 404

    data = request.get_json(force=True)

    # Update name if provided
    if 'name' in data and data['name'] is not None:
        db_user.name = data['name'].strip() or db_user.name

    # Update email if provided, checking uniqueness
    if 'email' in data and data['email'] is not None:
        new_email = data['email'].strip().lower()
        if new_email and new_email != db_user.email:
            existing = User.query.filter_by(email=new_email).first()
            if existing and existing.id != db_user.id:
                return jsonify({'error': 'Email already in use'}), 409
            db_user.email = new_email

    # Update phone if provided
    if 'phone' in data and data['phone'] is not None:
        new_phone = data['phone'].strip()
        if new_phone and new_phone != db_user.phone:
            existing = User.query.filter_by(phone=new_phone).first()
            if existing and existing.id != db_user.id:
                return jsonify({'error': 'Phone number already in use'}), 409
            db_user.phone = new_phone

    db.session.commit()

    return jsonify({
        'success': True,
        'user': db_user.to_dict()
    })


@auth_bp.route('/change-password', methods=['PUT'])
@require_auth
def change_password(user_id):
    """Change the current user's password"""
    from werkzeug.security import generate_password_hash

    db_user = db.session.get(User, user_id)
    if not db_user:
        return jsonify({'error': 'User not found'}), 404

    data = request.get_json(force=True)
    current_password = data.get('current_password')
    new_password = data.get('new_password')

    if not current_password or not new_password:
        return jsonify({'error': 'Current password and new password are required'}), 400

    if not db_user.check_password(current_password):
        return jsonify({'error': 'Current password is incorrect'}), 401

    if len(new_password) < 6:
        return jsonify({'error': 'New password must be at least 6 characters'}), 400

    db_user.password_hash = generate_password_hash(new_password)
    db.session.commit()

    return jsonify({
        'success': True,
        'message': 'Password changed successfully'
    })


@auth_bp.route('/me', methods=['DELETE'])
@require_auth
def delete_account(user_id):
    """Soft-delete the current user account (set status to deactivated)"""
    db_user = db.session.get(User, user_id)
    if not db_user:
        return jsonify({'error': 'User not found'}), 404

    db_user.status = 'deactivated'
    db.session.commit()

    return jsonify({
        'success': True,
        'message': 'Account deactivated successfully'
    })


# MARK: - Seed Admin

@auth_bp.route('/seed-admin', methods=['POST'])
def seed_admin():
    """Promote a user to admin role. Requires a seed secret."""
    import os
    data = request.get_json(force=True)
    secret = data.get('secret')
    email = data.get('email')

    # Use env var — no hardcoded fallback for security
    expected = os.environ.get('ADMIN_SEED_SECRET', '')
    if not expected:
        return jsonify({'error': 'ADMIN_SEED_SECRET is not configured'}), 503
    if secret != expected:
        return jsonify({'error': 'Unauthorized'}), 403

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({'error': 'User not found'}), 404

    user.role = 'admin'
    db.session.commit()
    return jsonify({'success': True, 'message': f'{email} is now admin'})


@auth_bp.route('/bootstrap-admin', methods=['POST'])
def bootstrap_admin():
    """One-time admin bootstrap. Only works when zero admins exist."""
    from werkzeug.security import generate_password_hash
    admin_count = User.query.filter_by(role='admin').count()
    if admin_count > 0:
        return jsonify({'error': 'Admin already exists. Use seed-admin instead.'}), 403

    data = request.get_json(force=True)
    email = data.get('email', 'admin@goumuve.com')
    password = data.get('password')
    name = data.get('name', 'Admin')

    if not password or len(password) < 8:
        return jsonify({'error': 'A password with at least 8 characters is required'}), 400

    user = User.query.filter_by(email=email).first()
    if user:
        user.role = 'admin'
        user.password_hash = generate_password_hash(password)
    else:
        user = User(
            email=email,
            name=name,
            role='admin',
            password_hash=generate_password_hash(password),
            referral_code=generate_referral_code(),
        )
        db.session.add(user)

    db.session.commit()
    return jsonify({'success': True, 'message': f'{email} is now admin', 'user_id': user.id})


# MARK: - Token Validation

@auth_bp.route('/validate', methods=['POST'])
def validate_token_endpoint():
    """Validate existing auth token"""
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user_id = verify_token(token)

    if not user_id:
        return jsonify({'error': 'Invalid token'}), 401

    # Check in-memory store
    if user_id in users_db:
        user = users_db[user_id]
        return jsonify({
            'success': True,
            'user': {
                'id': user['id'],
                'name': user.get('name'),
                'email': user.get('email'),
                'phoneNumber': user.get('phoneNumber'),
                'role': 'customer'
            }
        })

    # Check database
    db_user = db.session.get(User, user_id)
    if db_user:
        return jsonify({
            'success': True,
            'user': db_user.to_dict()
        })

    return jsonify({'error': 'User not found'}), 404


@auth_bp.route('/refresh', methods=['POST'])
def refresh_token_endpoint():
    """Refresh JWT token (allows refresh within 7 days of expiry)"""
    token = request.headers.get('Authorization', '').replace('Bearer ', '')

    try:
        # Decode with grace period (verify_token already handles expired check)
        # For refresh, we allow tokens expired up to 7 days
        payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'], options={'verify_exp': False})
        user_id = payload.get('user_id')
        exp = payload.get('exp')

        if not user_id or not exp:
            return jsonify({'error': 'Invalid token'}), 401

        # Check expiry with grace period
        exp_date = datetime.datetime.utcfromtimestamp(exp)
        now = datetime.datetime.utcnow()
        grace_period = datetime.timedelta(days=7)

        if now > exp_date + grace_period:
            return jsonify({'error': 'Token expired beyond refresh period'}), 401

        # Verify user still exists
        if user_id not in users_db and not db.session.get(User, user_id):
            return jsonify({'error': 'User not found'}), 404

        # Issue new token
        new_token = generate_token(user_id)

        return jsonify({
            'success': True,
            'token': new_token
        })

    except jwt.InvalidTokenError:
        return jsonify({'error': 'Invalid token'}), 401

# MARK: - Helper Functions

def find_or_create_user_by_phone(phone_number):
    """Find existing user by phone or create new one"""
    # Search for existing user
    for user_id, user in users_db.items():
        if user.get('phoneNumber') == phone_number:
            return user_id
    
    # Create new user
    user_id = secrets.token_hex(16)
    users_db[user_id] = {
        'id': user_id,
        'phoneNumber': phone_number,
        'email': None,
        'name': None
    }
    
    return user_id
