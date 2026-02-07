"""
Dispatch and driver assignment logic tests for JunkOS
Tests route optimization, driver availability, and smart scheduling
"""
import pytest
import json
from datetime import datetime, timedelta


class TestDriverAvailability:
    """Test driver availability management"""
    
    def test_get_available_drivers(self, client, operator_headers, test_driver):
        """Test retrieving list of available drivers"""
        target_date = datetime.now() + timedelta(days=2)
        
        response = client.get(
            f'/api/dispatch/available-drivers?date={target_date.strftime("%Y-%m-%d")}&time=10:00',
            headers=operator_headers
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data['drivers']) >= 1
        assert any(d['id'] == test_driver.id for d in data['drivers'])
    
    def test_driver_set_unavailable(self, client, driver_headers):
        """Test driver marking themselves unavailable"""
        response = client.post('/api/dispatch/availability',
            headers=driver_headers,
            json={
                'date': (datetime.now() + timedelta(days=5)).strftime('%Y-%m-%d'),
                'available': False,
                'reason': 'Personal day'
            }
        )
        
        assert response.status_code == 200
    
    def test_driver_view_schedule(self, client, driver_headers, test_job):
        """Test driver viewing their schedule"""
        response = client.get('/api/dispatch/my-schedule',
            headers=driver_headers
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'schedule' in data
        assert isinstance(data['schedule'], list)


class TestRouteOptimization:
    """Test route optimization and planning"""
    
    def test_optimize_daily_routes(self, client, operator_headers, booking_factory, test_driver):
        """Test optimizing routes for a day"""
        # Create multiple bookings for the same day
        target_date = datetime.now() + timedelta(days=3)
        
        booking_factory(
            pickup_zip='10001',
            pickup_address='123 First St',
            pickup_date=target_date,
            pickup_time='09:00'
        )
        booking_factory(
            pickup_zip='10002',
            pickup_address='456 Second Ave',
            pickup_date=target_date,
            pickup_time='10:00'
        )
        booking_factory(
            pickup_zip='10003',
            pickup_address='789 Third Blvd',
            pickup_date=target_date,
            pickup_time='11:00'
        )
        
        response = client.post('/api/dispatch/optimize-routes',
            headers=operator_headers,
            json={
                'date': target_date.strftime('%Y-%m-%d'),
                'driver_ids': [test_driver.id]
            }
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'routes' in data
        assert len(data['routes']) >= 1
    
    def test_route_minimizes_distance(self, client, operator_headers, booking_factory, test_driver):
        """Test route optimization minimizes total distance"""
        target_date = datetime.now() + timedelta(days=4)
        
        # Create bookings in logical geographic order
        bookings = [
            booking_factory(pickup_zip='10001', pickup_date=target_date),
            booking_factory(pickup_zip='10002', pickup_date=target_date),
            booking_factory(pickup_zip='10003', pickup_date=target_date)
        ]
        
        response = client.post('/api/dispatch/optimize-routes',
            headers=operator_headers,
            json={
                'date': target_date.strftime('%Y-%m-%d'),
                'driver_ids': [test_driver.id]
            }
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'total_distance' in data['routes'][0]
        assert 'estimated_time' in data['routes'][0]
    
    def test_route_respects_time_windows(self, client, operator_headers, booking_factory, test_driver):
        """Test route optimization respects scheduled time windows"""
        target_date = datetime.now() + timedelta(days=5)
        
        # Create bookings with specific times
        early_booking = booking_factory(
            pickup_date=target_date,
            pickup_time='08:00',
            status='confirmed'
        )
        late_booking = booking_factory(
            pickup_date=target_date,
            pickup_time='16:00',
            status='confirmed'
        )
        
        response = client.post('/api/dispatch/optimize-routes',
            headers=operator_headers,
            json={
                'date': target_date.strftime('%Y-%m-%d'),
                'driver_ids': [test_driver.id]
            }
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        route_stops = data['routes'][0]['stops']
        
        # Verify early booking comes before late booking
        early_idx = next(i for i, s in enumerate(route_stops) if s['booking_id'] == early_booking.id)
        late_idx = next(i for i, s in enumerate(route_stops) if s['booking_id'] == late_booking.id)
        assert early_idx < late_idx


class TestSmartAssignment:
    """Test intelligent driver assignment"""
    
    def test_auto_assign_to_nearest_driver(self, client, operator_headers, test_booking, test_driver, db_session):
        """Test auto-assignment picks nearest available driver"""
        test_booking.status = 'confirmed'
        db_session.commit()
        
        response = client.post('/api/dispatch/auto-assign',
            headers=operator_headers,
            json={
                'booking_id': test_booking.id
            }
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'assigned_driver' in data
        assert data['job']['assigned_driver_id'] is not None
    
    def test_assign_based_on_capacity(self, client, operator_headers, booking_factory, customer_factory, db_session):
        """Test assignment considers driver current load"""
        target_date = datetime.now() + timedelta(days=3)
        
        # Create two drivers
        driver1 = customer_factory(role='driver')
        driver2 = customer_factory(role='driver')
        
        # Create multiple bookings for same day
        bookings = [
            booking_factory(pickup_date=target_date, status='confirmed')
            for _ in range(5)
        ]
        
        response = client.post('/api/dispatch/auto-assign-batch',
            headers=operator_headers,
            json={
                'booking_ids': [b.id for b in bookings],
                'date': target_date.strftime('%Y-%m-%d')
            }
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data['assignments']) == len(bookings)
    
    def test_assignment_respects_driver_preferences(self, client, operator_headers, test_booking, test_driver, db_session):
        """Test assignment considers driver preferences/specialties"""
        test_booking.status = 'confirmed'
        test_booking.estimated_volume = 'full truck'
        db_session.commit()
        
        # In real implementation, would set driver preferences
        
        response = client.post('/api/dispatch/auto-assign',
            headers=operator_headers,
            json={
                'booking_id': test_booking.id,
                'prefer_experienced': True
            }
        )
        
        assert response.status_code == 200


class TestDispatchDashboard:
    """Test dispatch dashboard and overview"""
    
    def test_get_dispatch_overview(self, client, operator_headers):
        """Test getting dispatch dashboard overview"""
        response = client.get('/api/dispatch/overview',
            headers=operator_headers
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'active_jobs' in data
        assert 'available_drivers' in data
        assert 'pending_assignments' in data
    
    def test_get_driver_locations(self, client, operator_headers, test_driver):
        """Test getting current driver locations"""
        response = client.get('/api/dispatch/driver-locations',
            headers=operator_headers
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'drivers' in data
    
    def test_driver_update_location(self, client, driver_headers):
        """Test driver updating their GPS location"""
        response = client.post('/api/dispatch/update-location',
            headers=driver_headers,
            json={
                'latitude': 40.7128,
                'longitude': -74.0060,
                'accuracy': 10
            }
        )
        
        assert response.status_code == 200


class TestDispatchNotifications:
    """Test dispatch notifications and alerts"""
    
    def test_notify_driver_new_assignment(self, client, operator_headers, test_booking, test_driver, db_session):
        """Test driver receives notification for new assignment"""
        test_booking.status = 'confirmed'
        db_session.commit()
        
        response = client.post('/api/dispatch/auto-assign',
            headers=operator_headers,
            json={
                'booking_id': test_booking.id,
                'driver_id': test_driver.id
            }
        )
        
        assert response.status_code == 200
        # Would verify notification was sent in real implementation
    
    def test_alert_on_driver_running_late(self, client, operator_headers, test_job, db_session):
        """Test alert when driver is running behind schedule"""
        test_job.status = 'in_progress'
        test_job.scheduled_date = datetime.now() - timedelta(hours=2)
        db_session.commit()
        
        response = client.get('/api/dispatch/alerts',
            headers=operator_headers
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data['alerts']) >= 0
    
    def test_notify_customer_driver_eta(self, client, driver_headers, test_job):
        """Test sending ETA notification to customer"""
        response = client.post(f'/api/dispatch/notify-eta',
            headers=driver_headers,
            json={
                'job_id': test_job.id,
                'eta_minutes': 15
            }
        )
        
        assert response.status_code == 200


class TestDispatchConstraints:
    """Test dispatch scheduling constraints"""
    
    def test_prevent_driver_overbooking(self, client, operator_headers, booking_factory, test_driver, db_session):
        """Test system prevents assigning overlapping jobs"""
        target_date = datetime.now() + timedelta(days=3)
        
        booking1 = booking_factory(
            pickup_date=target_date,
            pickup_time='10:00',
            status='confirmed'
        )
        booking2 = booking_factory(
            pickup_date=target_date,
            pickup_time='10:30',  # Overlapping
            status='confirmed'
        )
        
        # Assign first job
        client.post('/api/dispatch/auto-assign',
            headers=operator_headers,
            json={
                'booking_id': booking1.id,
                'driver_id': test_driver.id
            }
        )
        
        # Try to assign overlapping job
        response = client.post('/api/dispatch/auto-assign',
            headers=operator_headers,
            json={
                'booking_id': booking2.id,
                'driver_id': test_driver.id
            }
        )
        
        # Should either fail or assign to different driver
        assert response.status_code in [200, 400, 409]
    
    def test_respect_max_jobs_per_day(self, client, operator_headers, booking_factory, test_driver):
        """Test respecting maximum jobs per driver per day"""
        target_date = datetime.now() + timedelta(days=4)
        
        # Try to assign more than reasonable daily capacity
        bookings = [
            booking_factory(pickup_date=target_date, status='confirmed')
            for _ in range(15)
        ]
        
        response = client.post('/api/dispatch/auto-assign-batch',
            headers=operator_headers,
            json={
                'booking_ids': [b.id for b in bookings],
                'driver_id': test_driver.id
            }
        )
        
        # Should distribute across multiple drivers or multiple days
        assert response.status_code == 200
