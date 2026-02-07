"""
Authentication Routes for JunkOS Backend
Handles phone verification, email login, and Apple Sign In
"""

from flask import Blueprint, request, jsonify
import secrets
import hashlib
import jwt
import datetime
from functools import wraps

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

# In-memory storage for demo (use Redis in production)
verification_codes = {}  # phone_number: {code, expires_at}
users_db = {}  # user_id: {id, name, email, phone, password_hash}

# JWT secret (use environment variable in production)
JWT_SECRET = secrets.token_hex(32)

# MARK: - Helper Functions

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
    
    # TODO: Send SMS via Twilio
    # For demo, print to console
    print(f"📱 SMS Code for {phone_number}: {code}")
    
    return jsonify({
        'success': True,
        'message': 'Verification code sent',
        # Include code in response for demo (remove in production!)
        'code': code
    })

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
def signup():
    """Create new user account with email/password"""
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    name = data.get('name')
    
    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400
    
    # Check if email already exists
    for user in users_db.values():
        if user.get('email') == email:
            return jsonify({'error': 'Email already registered'}), 409
    
    # Create user
    user_id = secrets.token_hex(16)
    users_db[user_id] = {
        'id': user_id,
        'email': email,
        'password_hash': hash_password(password),
        'name': name,
        'phoneNumber': None
    }
    
    # Generate token
    token = generate_token(user_id)
    
    return jsonify({
        'success': True,
        'token': token,
        'user': {
            'id': user_id,
            'name': name,
            'email': email,
            'phoneNumber': None
        }
    })

@auth_bp.route('/login', methods=['POST'])
def login():
    """Login with email and password"""
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    
    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400
    
    # Find user by email
    user = None
    for u in users_db.values():
        if u.get('email') == email:
            user = u
            break
    
    if not user:
        return jsonify({'error': 'Invalid email or password'}), 401
    
    # Verify password
    password_hash = hash_password(password)
    if user.get('password_hash') != password_hash:
        return jsonify({'error': 'Invalid email or password'}), 401
    
    # Generate token
    token = generate_token(user['id'])
    
    return jsonify({
        'success': True,
        'token': token,
        'user': {
            'id': user['id'],
            'name': user.get('name'),
            'email': user['email'],
            'phoneNumber': user.get('phoneNumber')
        }
    })

# MARK: - Apple Sign In

@auth_bp.route('/apple', methods=['POST'])
def apple_signin():
    """Authenticate with Apple Sign In credential"""
    data = request.get_json()
    user_identifier = data.get('userIdentifier')
    email = data.get('email')
    name = data.get('name')
    
    if not user_identifier:
        return jsonify({'error': 'Apple user identifier required'}), 400
    
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

# MARK: - Token Validation

@auth_bp.route('/validate', methods=['POST'])
def validate_token():
    """Validate existing auth token"""
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user_id = verify_token(token)
    
    if not user_id or user_id not in users_db:
        return jsonify({'error': 'Invalid token'}), 401
    
    user = users_db[user_id]
    
    return jsonify({
        'success': True,
        'user': {
            'id': user['id'],
            'name': user.get('name'),
            'email': user.get('email'),
            'phoneNumber': user.get('phoneNumber')
        }
    })

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
