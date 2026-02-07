"""
Authentication tests for JunkOS
Tests login, registration, JWT validation, and password reset
"""
import pytest
import json
from datetime import datetime, timedelta
import jwt


class TestRegistration:
    """Test user registration flows"""
    
    def test_register_customer_success(self, client, test_tenant):
        """Test successful customer registration"""
        response = client.post('/api/auth/register', 
            json={
                'email': 'newcustomer@example.com',
                'password': 'SecurePass123!',
                'first_name': 'New',
                'last_name': 'Customer',
                'phone': '555-1111',
                'tenant_subdomain': 'test'
            }
        )
        
        assert response.status_code == 201
        data = json.loads(response.data)
        assert data['user']['email'] == 'newcustomer@example.com'
        assert data['user']['role'] == 'customer'
        assert 'token' in data
    
    def test_register_duplicate_email(self, client, test_customer):
        """Test registration with existing email fails"""
        response = client.post('/api/auth/register',
            json={
                'email': test_customer.email,
                'password': 'SecurePass123!',
                'first_name': 'Duplicate',
                'last_name': 'User',
                'phone': '555-2222'
            }
        )
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'already exists' in data['message'].lower()
    
    def test_register_weak_password(self, client):
        """Test registration with weak password fails"""
        response = client.post('/api/auth/register',
            json={
                'email': 'weak@example.com',
                'password': '123',
                'first_name': 'Weak',
                'last_name': 'Password',
                'phone': '555-3333'
            }
        )
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'password' in data['message'].lower()
    
    def test_register_invalid_email(self, client):
        """Test registration with invalid email format fails"""
        response = client.post('/api/auth/register',
            json={
                'email': 'not-an-email',
                'password': 'SecurePass123!',
                'first_name': 'Invalid',
                'last_name': 'Email',
                'phone': '555-4444'
            }
        )
        
        assert response.status_code == 400


class TestLogin:
    """Test user login flows"""
    
    def test_login_success(self, client, test_customer):
        """Test successful login returns token"""
        response = client.post('/api/auth/login',
            json={
                'email': test_customer.email,
                'password': 'TestPass123!'
            }
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'token' in data
        assert data['user']['email'] == test_customer.email
        assert data['user']['role'] == 'customer'
    
    def test_login_wrong_password(self, client, test_customer):
        """Test login with incorrect password fails"""
        response = client.post('/api/auth/login',
            json={
                'email': test_customer.email,
                'password': 'WrongPassword123!'
            }
        )
        
        assert response.status_code == 401
        data = json.loads(response.data)
        assert 'invalid' in data['message'].lower()
    
    def test_login_nonexistent_user(self, client):
        """Test login with non-existent email fails"""
        response = client.post('/api/auth/login',
            json={
                'email': 'nonexistent@example.com',
                'password': 'TestPass123!'
            }
        )
        
        assert response.status_code == 401
    
    def test_login_inactive_user(self, client, test_customer, db_session):
        """Test login with inactive account fails"""
        test_customer.is_active = False
        db_session.commit()
        
        response = client.post('/api/auth/login',
            json={
                'email': test_customer.email,
                'password': 'TestPass123!'
            }
        )
        
        assert response.status_code == 403
        data = json.loads(response.data)
        assert 'inactive' in data['message'].lower()


class TestJWTValidation:
    """Test JWT token validation and refresh"""
    
    def test_protected_endpoint_with_valid_token(self, client, auth_headers):
        """Test accessing protected endpoint with valid token"""
        response = client.get('/api/bookings',
            headers=auth_headers
        )
        
        assert response.status_code in [200, 404]  # 404 if no bookings
    
    def test_protected_endpoint_without_token(self, client):
        """Test accessing protected endpoint without token fails"""
        response = client.get('/api/bookings')
        
        assert response.status_code == 401
    
    def test_protected_endpoint_with_invalid_token(self, client):
        """Test accessing protected endpoint with invalid token fails"""
        response = client.get('/api/bookings',
            headers={
                'Authorization': 'Bearer invalid.token.here',
                'Content-Type': 'application/json'
            }
        )
        
        assert response.status_code == 401
    
    def test_expired_token_rejected(self, client, app, test_customer):
        """Test that expired tokens are rejected"""
        expired_token = jwt.encode({
            'user_id': test_customer.id,
            'tenant_id': test_customer.tenant_id,
            'role': test_customer.role,
            'exp': datetime.utcnow() - timedelta(hours=1)
        }, app.config['SECRET_KEY'], algorithm='HS256')
        
        response = client.get('/api/bookings',
            headers={
                'Authorization': f'Bearer {expired_token}',
                'Content-Type': 'application/json'
            }
        )
        
        assert response.status_code == 401
    
    def test_token_refresh(self, client, auth_headers):
        """Test token refresh endpoint"""
        response = client.post('/api/auth/refresh',
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'token' in data


class TestPasswordReset:
    """Test password reset flows"""
    
    def test_request_password_reset(self, client, test_customer):
        """Test requesting password reset email"""
        response = client.post('/api/auth/forgot-password',
            json={
                'email': test_customer.email
            }
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'email sent' in data['message'].lower()
    
    def test_request_password_reset_nonexistent(self, client):
        """Test password reset for non-existent user still returns success (security)"""
        response = client.post('/api/auth/forgot-password',
            json={
                'email': 'nonexistent@example.com'
            }
        )
        
        # Should return success to prevent user enumeration
        assert response.status_code == 200
    
    def test_reset_password_with_valid_token(self, client, app, test_customer):
        """Test resetting password with valid token"""
        reset_token = jwt.encode({
            'user_id': test_customer.id,
            'purpose': 'password_reset',
            'exp': datetime.utcnow() + timedelta(hours=1)
        }, app.config['SECRET_KEY'], algorithm='HS256')
        
        response = client.post('/api/auth/reset-password',
            json={
                'token': reset_token,
                'new_password': 'NewSecurePass123!'
            }
        )
        
        assert response.status_code == 200
        
        # Verify can login with new password
        login_response = client.post('/api/auth/login',
            json={
                'email': test_customer.email,
                'password': 'NewSecurePass123!'
            }
        )
        assert login_response.status_code == 200


class TestAuthorization:
    """Test role-based access control"""
    
    def test_customer_cannot_access_operator_endpoint(self, client, auth_headers):
        """Test customer cannot access operator-only endpoints"""
        response = client.get('/api/dispatch/routes',
            headers=auth_headers
        )
        
        assert response.status_code == 403
    
    def test_operator_can_access_dispatch(self, client, operator_headers):
        """Test operator can access dispatch endpoints"""
        response = client.get('/api/dispatch/routes',
            headers=operator_headers
        )
        
        assert response.status_code in [200, 404]
    
    def test_driver_can_access_assigned_jobs(self, client, driver_headers, test_job):
        """Test driver can view their assigned jobs"""
        response = client.get(f'/api/jobs/{test_job.id}',
            headers=driver_headers
        )
        
        assert response.status_code == 200
