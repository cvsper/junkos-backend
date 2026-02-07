"""
Pytest configuration and fixtures for JunkOS backend tests
"""
import pytest
import os
from datetime import datetime, timedelta
from app import create_app, db
from app.models.user import User
from app.models.tenant import Tenant
from app.models.booking import Booking
from app.models.job import Job
import jwt


@pytest.fixture(scope='session')
def app():
    """Create application instance for testing"""
    os.environ['FLASK_ENV'] = 'testing'
    app = create_app('testing')
    
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture(scope='function')
def client(app):
    """Create test client"""
    return app.test_client()


@pytest.fixture(scope='function')
def db_session(app):
    """Create fresh database session for each test"""
    with app.app_context():
        # Begin a nested transaction
        connection = db.engine.connect()
        transaction = connection.begin()
        
        # Bind the session to the connection
        options = dict(bind=connection, binds={})
        session = db.create_scoped_session(options=options)
        db.session = session
        
        yield session
        
        # Rollback transaction and close
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def test_tenant(db_session):
    """Create a test tenant"""
    tenant = Tenant(
        name='Test Junk Removal Co',
        subdomain='test',
        email='test@junkremoval.com',
        phone='555-0123',
        status='active',
        plan='professional',
        settings={
            'business_hours': {
                'monday': {'open': '08:00', 'close': '18:00'},
                'tuesday': {'open': '08:00', 'close': '18:00'},
                'wednesday': {'open': '08:00', 'close': '18:00'},
                'thursday': {'open': '08:00', 'close': '18:00'},
                'friday': {'open': '08:00', 'close': '18:00'},
                'saturday': {'open': '09:00', 'close': '15:00'},
                'sunday': {'open': None, 'close': None}
            },
            'service_area': {
                'zip_codes': ['10001', '10002', '10003']
            }
        }
    )
    db_session.add(tenant)
    db_session.commit()
    return tenant


@pytest.fixture
def test_customer(db_session, test_tenant):
    """Create a test customer user"""
    user = User(
        email='customer@example.com',
        first_name='John',
        last_name='Customer',
        phone='555-1234',
        tenant_id=test_tenant.id,
        role='customer',
        is_active=True
    )
    user.set_password('TestPass123!')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def test_operator(db_session, test_tenant):
    """Create a test operator user"""
    user = User(
        email='operator@example.com',
        first_name='Jane',
        last_name='Operator',
        phone='555-5678',
        tenant_id=test_tenant.id,
        role='operator',
        is_active=True
    )
    user.set_password('OperatorPass123!')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def test_driver(db_session, test_tenant):
    """Create a test driver user"""
    user = User(
        email='driver@example.com',
        first_name='Bob',
        last_name='Driver',
        phone='555-9999',
        tenant_id=test_tenant.id,
        role='driver',
        is_active=True
    )
    user.set_password('DriverPass123!')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def auth_headers(app, test_customer):
    """Generate auth headers with JWT token for customer"""
    token = jwt.encode({
        'user_id': test_customer.id,
        'tenant_id': test_customer.tenant_id,
        'role': test_customer.role,
        'exp': datetime.utcnow() + timedelta(hours=1)
    }, app.config['SECRET_KEY'], algorithm='HS256')
    
    return {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }


@pytest.fixture
def operator_headers(app, test_operator):
    """Generate auth headers with JWT token for operator"""
    token = jwt.encode({
        'user_id': test_operator.id,
        'tenant_id': test_operator.tenant_id,
        'role': test_operator.role,
        'exp': datetime.utcnow() + timedelta(hours=1)
    }, app.config['SECRET_KEY'], algorithm='HS256')
    
    return {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }


@pytest.fixture
def driver_headers(app, test_driver):
    """Generate auth headers with JWT token for driver"""
    token = jwt.encode({
        'user_id': test_driver.id,
        'tenant_id': test_driver.tenant_id,
        'role': test_driver.role,
        'exp': datetime.utcnow() + timedelta(hours=1)
    }, app.config['SECRET_KEY'], algorithm='HS256')
    
    return {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }


@pytest.fixture
def test_booking(db_session, test_customer, test_tenant):
    """Create a test booking"""
    booking = Booking(
        tenant_id=test_tenant.id,
        customer_id=test_customer.id,
        pickup_address='123 Test St',
        pickup_city='New York',
        pickup_state='NY',
        pickup_zip='10001',
        pickup_date=datetime.now() + timedelta(days=2),
        pickup_time='10:00',
        items=['Sofa', 'Refrigerator', 'Mattress'],
        photos=['https://example.com/photo1.jpg'],
        estimated_volume='1/4 truck',
        estimated_price=250.00,
        status='pending'
    )
    db_session.add(booking)
    db_session.commit()
    return booking


@pytest.fixture
def test_job(db_session, test_booking, test_driver):
    """Create a test job"""
    job = Job(
        tenant_id=test_booking.tenant_id,
        booking_id=test_booking.id,
        assigned_driver_id=test_driver.id,
        scheduled_date=test_booking.pickup_date,
        scheduled_time=test_booking.pickup_time,
        status='scheduled',
        estimated_duration=90
    )
    db_session.add(job)
    db_session.commit()
    return job


# Factory fixtures using factory_boy
@pytest.fixture
def customer_factory(db_session, test_tenant):
    """Factory for creating multiple test customers"""
    def _create_customer(**kwargs):
        defaults = {
            'email': f'customer_{datetime.now().timestamp()}@example.com',
            'first_name': 'Test',
            'last_name': 'Customer',
            'phone': '555-0000',
            'tenant_id': test_tenant.id,
            'role': 'customer',
            'is_active': True
        }
        defaults.update(kwargs)
        
        user = User(**defaults)
        user.set_password('TestPass123!')
        db_session.add(user)
        db_session.commit()
        return user
    
    return _create_customer


@pytest.fixture
def booking_factory(db_session, test_customer, test_tenant):
    """Factory for creating multiple test bookings"""
    def _create_booking(**kwargs):
        defaults = {
            'tenant_id': test_tenant.id,
            'customer_id': test_customer.id,
            'pickup_address': '123 Test St',
            'pickup_city': 'New York',
            'pickup_state': 'NY',
            'pickup_zip': '10001',
            'pickup_date': datetime.now() + timedelta(days=2),
            'pickup_time': '10:00',
            'items': ['Test Item'],
            'estimated_volume': '1/4 truck',
            'estimated_price': 200.00,
            'status': 'pending'
        }
        defaults.update(kwargs)
        
        booking = Booking(**defaults)
        db_session.add(booking)
        db_session.commit()
        return booking
    
    return _create_booking
