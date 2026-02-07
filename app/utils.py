import jwt
import bcrypt
from datetime import datetime, timedelta
from functools import wraps
from flask import request, jsonify, current_app
from app.models import User


def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash"""
    return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))


def generate_token(user_id: str, tenant_id: str, role: str) -> str:
    """Generate JWT token with user and tenant information"""
    payload = {
        'user_id': user_id,
        'tenant_id': tenant_id,
        'role': role,
        'exp': datetime.utcnow() + current_app.config['JWT_ACCESS_TOKEN_EXPIRES'],
        'iat': datetime.utcnow()
    }
    return jwt.encode(
        payload,
        current_app.config['JWT_SECRET_KEY'],
        algorithm=current_app.config['JWT_ALGORITHM']
    )


def decode_token(token: str) -> dict:
    """Decode and verify JWT token"""
    try:
        return jwt.decode(
            token,
            current_app.config['JWT_SECRET_KEY'],
            algorithms=[current_app.config['JWT_ALGORITHM']]
        )
    except jwt.ExpiredSignatureError:
        raise ValueError('Token has expired')
    except jwt.InvalidTokenError:
        raise ValueError('Invalid token')


def require_auth(f):
    """Decorator to require authentication for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        
        if not auth_header:
            return jsonify({'error': 'Missing authorization header'}), 401
        
        try:
            # Extract token from "Bearer <token>"
            token = auth_header.split(' ')[1] if ' ' in auth_header else auth_header
            payload = decode_token(token)
            
            # Attach user info to request
            request.user_id = payload['user_id']
            request.tenant_id = payload['tenant_id']
            request.user_role = payload['role']
            
        except (ValueError, IndexError) as e:
            return jsonify({'error': str(e)}), 401
        
        return f(*args, **kwargs)
    
    return decorated_function


def require_role(*roles):
    """Decorator to require specific role(s) for routes"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not hasattr(request, 'user_role'):
                return jsonify({'error': 'Authentication required'}), 401
            
            if request.user_role not in roles:
                return jsonify({'error': 'Insufficient permissions'}), 403
            
            return f(*args, **kwargs)
        
        return decorated_function
    return decorator


def paginate_query(query, page=1, per_page=20):
    """Helper to paginate SQLAlchemy queries"""
    page = max(1, page)
    per_page = min(100, max(1, per_page))  # Cap at 100 items per page
    
    paginated = query.paginate(page=page, per_page=per_page, error_out=False)
    
    return {
        'items': paginated.items,
        'total': paginated.total,
        'page': page,
        'per_page': per_page,
        'pages': paginated.pages,
        'has_next': paginated.has_next,
        'has_prev': paginated.has_prev
    }


def serialize_model(model):
    """Convert SQLAlchemy model to dict"""
    if model is None:
        return None
    
    result = {}
    for column in model.__table__.columns:
        value = getattr(model, column.name)
        
        # Handle special types
        if isinstance(value, datetime):
            result[column.name] = value.isoformat()
        elif hasattr(value, '__float__'):  # Numeric types
            result[column.name] = float(value)
        else:
            result[column.name] = value
    
    return result
