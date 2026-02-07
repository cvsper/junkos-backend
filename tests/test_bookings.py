"""
Booking CRUD operations tests for JunkOS
Tests creating, reading, updating, and deleting bookings
"""
import pytest
import json
from datetime import datetime, timedelta


class TestCreateBooking:
    """Test booking creation"""
    
    def test_create_booking_success(self, client, auth_headers, test_tenant):
        """Test successful booking creation"""
        booking_data = {
            'pickup_address': '456 Oak Ave',
            'pickup_city': 'New York',
            'pickup_state': 'NY',
            'pickup_zip': '10001',
            'pickup_date': (datetime.now() + timedelta(days=3)).strftime('%Y-%m-%d'),
            'pickup_time': '14:00',
            'items': ['Couch', 'Table', 'Chairs'],
            'photos': ['https://example.com/photo1.jpg'],
            'estimated_volume': '1/2 truck',
            'notes': 'Please call when arriving'
        }
        
        response = client.post('/api/bookings',
            headers=auth_headers,
            json=booking_data
        )
        
        assert response.status_code == 201
        data = json.loads(response.data)
        assert data['booking']['pickup_address'] == '456 Oak Ave'
        assert data['booking']['status'] == 'pending'
        assert len(data['booking']['items']) == 3
    
    def test_create_booking_with_photos(self, client, auth_headers):
        """Test creating booking with multiple photos"""
        booking_data = {
            'pickup_address': '789 Pine St',
            'pickup_city': 'New York',
            'pickup_state': 'NY',
            'pickup_zip': '10002',
            'pickup_date': (datetime.now() + timedelta(days=5)).strftime('%Y-%m-%d'),
            'pickup_time': '10:00',
            'items': ['Refrigerator'],
            'photos': [
                'https://example.com/photo1.jpg',
                'https://example.com/photo2.jpg',
                'https://example.com/photo3.jpg'
            ],
            'estimated_volume': '1/4 truck'
        }
        
        response = client.post('/api/bookings',
            headers=auth_headers,
            json=booking_data
        )
        
        assert response.status_code == 201
        data = json.loads(response.data)
        assert len(data['booking']['photos']) == 3
    
    def test_create_booking_missing_required_fields(self, client, auth_headers):
        """Test booking creation fails with missing required fields"""
        booking_data = {
            'pickup_address': '123 Test St',
            # Missing other required fields
        }
        
        response = client.post('/api/bookings',
            headers=auth_headers,
            json=booking_data
        )
        
        assert response.status_code == 400
    
    def test_create_booking_invalid_date(self, client, auth_headers):
        """Test booking creation fails with past date"""
        booking_data = {
            'pickup_address': '123 Test St',
            'pickup_city': 'New York',
            'pickup_state': 'NY',
            'pickup_zip': '10001',
            'pickup_date': (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d'),
            'pickup_time': '10:00',
            'items': ['Sofa'],
            'estimated_volume': '1/4 truck'
        }
        
        response = client.post('/api/bookings',
            headers=auth_headers,
            json=booking_data
        )
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'date' in data['message'].lower()
    
    def test_create_booking_outside_service_area(self, client, auth_headers):
        """Test booking creation fails for unsupported zip code"""
        booking_data = {
            'pickup_address': '123 Remote St',
            'pickup_city': 'Far Away',
            'pickup_state': 'CA',
            'pickup_zip': '90210',  # Not in service area
            'pickup_date': (datetime.now() + timedelta(days=3)).strftime('%Y-%m-%d'),
            'pickup_time': '10:00',
            'items': ['Sofa'],
            'estimated_volume': '1/4 truck'
        }
        
        response = client.post('/api/bookings',
            headers=auth_headers,
            json=booking_data
        )
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'service area' in data['message'].lower()


class TestReadBookings:
    """Test booking retrieval"""
    
    def test_get_own_bookings(self, client, auth_headers, test_booking):
        """Test customer can retrieve their own bookings"""
        response = client.get('/api/bookings',
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data['bookings']) >= 1
        assert any(b['id'] == test_booking.id for b in data['bookings'])
    
    def test_get_booking_by_id(self, client, auth_headers, test_booking):
        """Test retrieving specific booking by ID"""
        response = client.get(f'/api/bookings/{test_booking.id}',
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['booking']['id'] == test_booking.id
        assert data['booking']['pickup_address'] == test_booking.pickup_address
    
    def test_get_booking_not_found(self, client, auth_headers):
        """Test retrieving non-existent booking returns 404"""
        response = client.get('/api/bookings/99999',
            headers=auth_headers
        )
        
        assert response.status_code == 404
    
    def test_customer_cannot_view_other_bookings(self, client, auth_headers, booking_factory, customer_factory):
        """Test customer cannot view another customer's bookings"""
        other_customer = customer_factory()
        other_booking = booking_factory(customer_id=other_customer.id)
        
        response = client.get(f'/api/bookings/{other_booking.id}',
            headers=auth_headers
        )
        
        assert response.status_code == 403
    
    def test_operator_can_view_all_bookings(self, client, operator_headers, test_booking):
        """Test operator can view all tenant bookings"""
        response = client.get('/api/bookings',
            headers=operator_headers
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data['bookings']) >= 1
    
    def test_filter_bookings_by_status(self, client, operator_headers, booking_factory):
        """Test filtering bookings by status"""
        booking_factory(status='pending')
        booking_factory(status='confirmed')
        booking_factory(status='completed')
        
        response = client.get('/api/bookings?status=pending',
            headers=operator_headers
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert all(b['status'] == 'pending' for b in data['bookings'])
    
    def test_filter_bookings_by_date_range(self, client, operator_headers, booking_factory):
        """Test filtering bookings by date range"""
        start_date = datetime.now() + timedelta(days=1)
        end_date = datetime.now() + timedelta(days=7)
        
        response = client.get(
            f'/api/bookings?start_date={start_date.strftime("%Y-%m-%d")}&end_date={end_date.strftime("%Y-%m-%d")}',
            headers=operator_headers
        )
        
        assert response.status_code == 200


class TestUpdateBooking:
    """Test booking updates"""
    
    def test_update_booking_address(self, client, auth_headers, test_booking):
        """Test updating booking address"""
        response = client.patch(f'/api/bookings/{test_booking.id}',
            headers=auth_headers,
            json={
                'pickup_address': '999 Updated St',
                'pickup_city': 'New York',
                'pickup_zip': '10001'
            }
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['booking']['pickup_address'] == '999 Updated St'
    
    def test_update_booking_items(self, client, auth_headers, test_booking):
        """Test updating booking items"""
        new_items = ['Updated Item 1', 'Updated Item 2']
        
        response = client.patch(f'/api/bookings/{test_booking.id}',
            headers=auth_headers,
            json={'items': new_items}
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['booking']['items'] == new_items
    
    def test_customer_cannot_update_after_confirmation(self, client, auth_headers, test_booking, db_session):
        """Test customer cannot update confirmed booking"""
        test_booking.status = 'confirmed'
        db_session.commit()
        
        response = client.patch(f'/api/bookings/{test_booking.id}',
            headers=auth_headers,
            json={'pickup_address': '123 New St'}
        )
        
        assert response.status_code == 403
    
    def test_operator_can_update_confirmed_booking(self, client, operator_headers, test_booking, db_session):
        """Test operator can update confirmed bookings"""
        test_booking.status = 'confirmed'
        db_session.commit()
        
        response = client.patch(f'/api/bookings/{test_booking.id}',
            headers=operator_headers,
            json={'notes': 'Operator note added'}
        )
        
        assert response.status_code == 200


class TestCancelBooking:
    """Test booking cancellation"""
    
    def test_cancel_pending_booking(self, client, auth_headers, test_booking):
        """Test canceling pending booking"""
        response = client.post(f'/api/bookings/{test_booking.id}/cancel',
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['booking']['status'] == 'cancelled'
    
    def test_cannot_cancel_completed_booking(self, client, auth_headers, test_booking, db_session):
        """Test cannot cancel completed booking"""
        test_booking.status = 'completed'
        db_session.commit()
        
        response = client.post(f'/api/bookings/{test_booking.id}/cancel',
            headers=auth_headers
        )
        
        assert response.status_code == 400
    
    def test_late_cancellation_fee(self, client, auth_headers, test_booking, db_session):
        """Test late cancellation incurs fee"""
        # Set pickup to within 24 hours
        test_booking.pickup_date = datetime.now() + timedelta(hours=12)
        db_session.commit()
        
        response = client.post(f'/api/bookings/{test_booking.id}/cancel',
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'cancellation_fee' in data['booking']
        assert data['booking']['cancellation_fee'] > 0


class TestBookingEstimate:
    """Test booking price estimation"""
    
    def test_get_price_estimate(self, client, auth_headers):
        """Test getting price estimate before booking"""
        response = client.post('/api/bookings/estimate',
            headers=auth_headers,
            json={
                'pickup_zip': '10001',
                'estimated_volume': '1/2 truck',
                'items': ['Sofa', 'Refrigerator', 'Mattress']
            }
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'estimated_price' in data
        assert data['estimated_price'] > 0
    
    def test_estimate_varies_by_volume(self, client, auth_headers):
        """Test price estimate increases with volume"""
        quarter_truck = client.post('/api/bookings/estimate',
            headers=auth_headers,
            json={
                'pickup_zip': '10001',
                'estimated_volume': '1/4 truck',
                'items': ['Chair']
            }
        )
        
        half_truck = client.post('/api/bookings/estimate',
            headers=auth_headers,
            json={
                'pickup_zip': '10001',
                'estimated_volume': '1/2 truck',
                'items': ['Sofa', 'Table']
            }
        )
        
        quarter_price = json.loads(quarter_truck.data)['estimated_price']
        half_price = json.loads(half_truck.data)['estimated_price']
        
        assert half_price > quarter_price
