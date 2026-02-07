from flask import Flask, request, jsonify
from flask_cors import CORS
from functools import wraps
from datetime import datetime, timedelta
import os

from app_config import Config
from database import Database
from auth_routes import auth_bp

app = Flask(__name__)
app.config.from_object(Config)
CORS(app)

db = Database(app.config['DATABASE_PATH'])

# Register blueprints
app.register_blueprint(auth_bp)

# Authentication decorator
def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if api_key != app.config['API_KEY']:
            return jsonify({'error': 'Invalid or missing API key'}), 401
        return f(*args, **kwargs)
    return decorated_function

# Helper functions
def calculate_price(service_ids, zip_code):
    """Calculate estimated price based on services"""
    total = 0
    services = []
    
    for service_id in service_ids:
        service = db.get_service(service_id)
        if service:
            total += service['base_price']
            services.append(service)
    
    # Add base service fee if not already included
    if len(services) > 0 and total < app.config['BASE_PRICE']:
        total += app.config['BASE_PRICE']
    
    return round(total, 2), services

def get_available_time_slots(requested_date=None):
    """Generate available time slots for booking"""
    slots = []
    start_date = datetime.now() + timedelta(days=1)  # Next day earliest
    
    if requested_date:
        try:
            start_date = datetime.strptime(requested_date, '%Y-%m-%d')
        except:
            pass
    
    # Generate 7 days of slots
    for day_offset in range(7):
        date = start_date + timedelta(days=day_offset)
        # Morning and afternoon slots
        for hour in [9, 13]:
            slot_time = date.replace(hour=hour, minute=0, second=0)
            slots.append(slot_time.strftime('%Y-%m-%d %H:%M'))
    
    return slots[:10]  # Return next 10 available slots

# API Routes
@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'service': 'JunkOS API'}), 200

@app.route('/api/services', methods=['GET'])
@require_api_key
def get_services():
    """Get all available services"""
    try:
        services = db.get_services()
        return jsonify({
            'success': True,
            'services': services
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/quote', methods=['POST'])
@require_api_key
def get_quote():
    """Get instant price quote"""
    try:
        data = request.get_json()
        
        if not data.get('services') or not isinstance(data['services'], list):
            return jsonify({'error': 'Services array is required'}), 400
        
        zip_code = data.get('zip_code', '')
        service_ids = data['services']
        
        estimated_price, services = calculate_price(service_ids, zip_code)
        available_slots = get_available_time_slots()
        
        return jsonify({
            'success': True,
            'estimated_price': estimated_price,
            'services': services,
            'available_time_slots': available_slots,
            'currency': 'USD'
        }), 200
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/bookings', methods=['POST'])
@require_api_key
def create_booking():
    """Create new booking"""
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['address', 'services', 'scheduled_datetime', 'customer']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        customer_data = data['customer']
        required_customer_fields = ['name', 'email', 'phone']
        for field in required_customer_fields:
            if field not in customer_data:
                return jsonify({'error': f'Missing customer field: {field}'}), 400
        
        # Create or get customer
        customer_id = db.create_customer(
            customer_data['name'],
            customer_data['email'],
            customer_data['phone']
        )
        
        # Calculate price
        estimated_price, services = calculate_price(
            data['services'],
            data.get('zip_code', '')
        )
        
        # Create booking
        booking_id = db.create_booking(
            customer_id=customer_id,
            address=data['address'],
            zip_code=data.get('zip_code', ''),
            services=data['services'],
            photos=data.get('photos', []),
            scheduled_datetime=data['scheduled_datetime'],
            estimated_price=estimated_price,
            notes=data.get('notes', '')
        )
        
        return jsonify({
            'success': True,
            'booking_id': booking_id,
            'estimated_price': estimated_price,
            'confirmation': f'Booking #{booking_id} confirmed',
            'scheduled_datetime': data['scheduled_datetime'],
            'services': services
        }), 201
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/bookings/<int:booking_id>', methods=['GET'])
@require_api_key
def get_booking(booking_id):
    """Get booking details"""
    try:
        booking = db.get_booking(booking_id)
        
        if not booking:
            return jsonify({'error': 'Booking not found'}), 404
        
        return jsonify({
            'success': True,
            'booking': booking
        }), 200
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    debug = os.environ.get('FLASK_ENV', 'development') == 'development'
    app.run(debug=debug, host='0.0.0.0', port=port)
