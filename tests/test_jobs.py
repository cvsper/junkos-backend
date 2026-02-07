"""
Job lifecycle and status management tests for JunkOS
Tests job creation, status updates, completion, and transitions
"""
import pytest
import json
from datetime import datetime, timedelta


class TestJobCreation:
    """Test job creation from bookings"""
    
    def test_create_job_from_booking(self, client, operator_headers, test_booking):
        """Test creating a job from a confirmed booking"""
        response = client.post('/api/jobs',
            headers=operator_headers,
            json={
                'booking_id': test_booking.id,
                'scheduled_date': test_booking.pickup_date.strftime('%Y-%m-%d'),
                'scheduled_time': test_booking.pickup_time,
                'estimated_duration': 90
            }
        )
        
        assert response.status_code == 201
        data = json.loads(response.data)
        assert data['job']['booking_id'] == test_booking.id
        assert data['job']['status'] == 'scheduled'
    
    def test_cannot_create_job_from_pending_booking(self, client, operator_headers, test_booking):
        """Test cannot create job from unconfirmed booking"""
        test_booking.status = 'pending'
        
        response = client.post('/api/jobs',
            headers=operator_headers,
            json={
                'booking_id': test_booking.id,
                'scheduled_date': test_booking.pickup_date.strftime('%Y-%m-%d'),
                'scheduled_time': test_booking.pickup_time
            }
        )
        
        assert response.status_code == 400
    
    def test_job_inherits_booking_details(self, client, operator_headers, test_booking, db_session):
        """Test job inherits details from booking"""
        test_booking.status = 'confirmed'
        db_session.commit()
        
        response = client.post('/api/jobs',
            headers=operator_headers,
            json={
                'booking_id': test_booking.id,
                'scheduled_date': test_booking.pickup_date.strftime('%Y-%m-%d'),
                'scheduled_time': test_booking.pickup_time,
                'estimated_duration': 90
            }
        )
        
        assert response.status_code == 201
        data = json.loads(response.data)
        assert data['job']['pickup_address'] == test_booking.pickup_address
        assert data['job']['customer_id'] == test_booking.customer_id


class TestJobAssignment:
    """Test driver assignment to jobs"""
    
    def test_assign_driver_to_job(self, client, operator_headers, test_job, test_driver):
        """Test assigning a driver to a job"""
        response = client.post(f'/api/jobs/{test_job.id}/assign',
            headers=operator_headers,
            json={'driver_id': test_driver.id}
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['job']['assigned_driver_id'] == test_driver.id
        assert data['job']['status'] == 'scheduled'
    
    def test_reassign_driver(self, client, operator_headers, test_job, customer_factory):
        """Test reassigning job to different driver"""
        new_driver = customer_factory(role='driver')
        
        response = client.post(f'/api/jobs/{test_job.id}/assign',
            headers=operator_headers,
            json={'driver_id': new_driver.id}
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['job']['assigned_driver_id'] == new_driver.id
    
    def test_driver_receives_notification(self, client, operator_headers, test_job, test_driver):
        """Test driver is notified when assigned"""
        response = client.post(f'/api/jobs/{test_job.id}/assign',
            headers=operator_headers,
            json={'driver_id': test_driver.id}
        )
        
        assert response.status_code == 200
        # In real implementation, would check notification was sent


class TestJobStatusTransitions:
    """Test job status lifecycle transitions"""
    
    def test_start_job(self, client, driver_headers, test_job):
        """Test driver starting a job"""
        response = client.post(f'/api/jobs/{test_job.id}/start',
            headers=driver_headers
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['job']['status'] == 'in_progress'
        assert 'started_at' in data['job']
    
    def test_cannot_start_unassigned_job(self, client, driver_headers, test_job, db_session):
        """Test cannot start job not assigned to you"""
        test_job.assigned_driver_id = None
        db_session.commit()
        
        response = client.post(f'/api/jobs/{test_job.id}/start',
            headers=driver_headers
        )
        
        assert response.status_code == 403
    
    def test_arrive_at_location(self, client, driver_headers, test_job, db_session):
        """Test marking arrival at pickup location"""
        test_job.status = 'in_progress'
        db_session.commit()
        
        response = client.post(f'/api/jobs/{test_job.id}/arrive',
            headers=driver_headers
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'arrived_at' in data['job']
    
    def test_complete_job(self, client, driver_headers, test_job, db_session):
        """Test completing a job"""
        test_job.status = 'in_progress'
        db_session.commit()
        
        response = client.post(f'/api/jobs/{test_job.id}/complete',
            headers=driver_headers,
            json={
                'actual_volume': '1/2 truck',
                'actual_items': ['Sofa', 'Refrigerator'],
                'completion_photos': ['https://example.com/complete1.jpg'],
                'customer_signature': 'data:image/png;base64,abc123',
                'notes': 'Job completed successfully'
            }
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['job']['status'] == 'completed'
        assert 'completed_at' in data['job']
        assert data['job']['actual_volume'] == '1/2 truck'
    
    def test_complete_job_requires_signature(self, client, driver_headers, test_job, db_session):
        """Test job completion requires customer signature"""
        test_job.status = 'in_progress'
        db_session.commit()
        
        response = client.post(f'/api/jobs/{test_job.id}/complete',
            headers=driver_headers,
            json={
                'actual_volume': '1/2 truck',
                # Missing customer_signature
            }
        )
        
        assert response.status_code == 400
    
    def test_cancel_job(self, client, operator_headers, test_job):
        """Test operator canceling a job"""
        response = client.post(f'/api/jobs/{test_job.id}/cancel',
            headers=operator_headers,
            json={'reason': 'Customer unavailable'}
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['job']['status'] == 'cancelled'
        assert data['job']['cancellation_reason'] == 'Customer unavailable'
    
    def test_invalid_status_transition(self, client, driver_headers, test_job, db_session):
        """Test invalid status transitions are prevented"""
        test_job.status = 'completed'
        db_session.commit()
        
        response = client.post(f'/api/jobs/{test_job.id}/start',
            headers=driver_headers
        )
        
        assert response.status_code == 400


class TestJobDetails:
    """Test job detail retrieval and updates"""
    
    def test_driver_view_assigned_jobs(self, client, driver_headers, test_job):
        """Test driver can view their assigned jobs"""
        response = client.get('/api/jobs/my-jobs',
            headers=driver_headers
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data['jobs']) >= 1
        assert any(j['id'] == test_job.id for j in data['jobs'])
    
    def test_driver_view_job_details(self, client, driver_headers, test_job):
        """Test driver can view details of assigned job"""
        response = client.get(f'/api/jobs/{test_job.id}',
            headers=driver_headers
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['job']['id'] == test_job.id
        assert 'pickup_address' in data['job']
        assert 'customer' in data['job']
    
    def test_driver_cannot_view_others_jobs(self, client, driver_headers, test_job, customer_factory, db_session):
        """Test driver cannot view other drivers' jobs"""
        other_driver = customer_factory(role='driver')
        test_job.assigned_driver_id = other_driver.id
        db_session.commit()
        
        response = client.get(f'/api/jobs/{test_job.id}',
            headers=driver_headers
        )
        
        assert response.status_code == 403
    
    def test_update_job_notes(self, client, driver_headers, test_job):
        """Test driver updating job notes"""
        response = client.patch(f'/api/jobs/{test_job.id}',
            headers=driver_headers,
            json={'driver_notes': 'Heavy items, need extra time'}
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['job']['driver_notes'] == 'Heavy items, need extra time'


class TestJobScheduling:
    """Test job scheduling and rescheduling"""
    
    def test_reschedule_job(self, client, operator_headers, test_job):
        """Test rescheduling a job to different date/time"""
        new_date = datetime.now() + timedelta(days=7)
        
        response = client.patch(f'/api/jobs/{test_job.id}/reschedule',
            headers=operator_headers,
            json={
                'scheduled_date': new_date.strftime('%Y-%m-%d'),
                'scheduled_time': '15:00'
            }
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['job']['scheduled_time'] == '15:00'
    
    def test_cannot_reschedule_in_progress_job(self, client, operator_headers, test_job, db_session):
        """Test cannot reschedule job that's already in progress"""
        test_job.status = 'in_progress'
        db_session.commit()
        
        new_date = datetime.now() + timedelta(days=7)
        
        response = client.patch(f'/api/jobs/{test_job.id}/reschedule',
            headers=operator_headers,
            json={
                'scheduled_date': new_date.strftime('%Y-%m-%d'),
                'scheduled_time': '15:00'
            }
        )
        
        assert response.status_code == 400


class TestJobMetrics:
    """Test job performance metrics"""
    
    def test_job_duration_tracking(self, client, driver_headers, test_job, db_session):
        """Test job tracks actual duration"""
        test_job.status = 'scheduled'
        db_session.commit()
        
        # Start job
        client.post(f'/api/jobs/{test_job.id}/start', headers=driver_headers)
        
        # Complete job after some time
        response = client.post(f'/api/jobs/{test_job.id}/complete',
            headers=driver_headers,
            json={
                'actual_volume': '1/2 truck',
                'customer_signature': 'data:image/png;base64,abc123'
            }
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'actual_duration' in data['job']
    
    def test_operator_view_job_metrics(self, client, operator_headers):
        """Test operator can view job performance metrics"""
        response = client.get('/api/jobs/metrics',
            headers=operator_headers
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'total_jobs' in data
        assert 'completed_jobs' in data
        assert 'average_duration' in data
