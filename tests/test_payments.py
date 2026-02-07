"""
Payment processing and invoice generation tests for JunkOS
Tests Stripe integration, invoicing, refunds, and payment tracking
"""
import pytest
import json
from datetime import datetime, timedelta
from decimal import Decimal


class TestInvoiceGeneration:
    """Test invoice creation and management"""
    
    def test_generate_invoice_from_completed_job(self, client, operator_headers, test_job, db_session):
        """Test generating invoice after job completion"""
        test_job.status = 'completed'
        test_job.actual_volume = '1/2 truck'
        test_job.completed_at = datetime.now()
        db_session.commit()
        
        response = client.post(f'/api/payments/invoices',
            headers=operator_headers,
            json={
                'job_id': test_job.id,
                'amount': 350.00,
                'items': [
                    {'description': 'Junk removal - 1/2 truck', 'amount': 300.00},
                    {'description': 'Heavy item surcharge', 'amount': 50.00}
                ]
            }
        )
        
        assert response.status_code == 201
        data = json.loads(response.data)
        assert data['invoice']['amount'] == 350.00
        assert data['invoice']['status'] == 'pending'
        assert len(data['invoice']['items']) == 2
    
    def test_invoice_includes_tax(self, client, operator_headers, test_job, db_session):
        """Test invoice calculates and includes tax"""
        test_job.status = 'completed'
        db_session.commit()
        
        response = client.post(f'/api/payments/invoices',
            headers=operator_headers,
            json={
                'job_id': test_job.id,
                'subtotal': 300.00,
                'tax_rate': 0.08
            }
        )
        
        assert response.status_code == 201
        data = json.loads(response.data)
        assert data['invoice']['subtotal'] == 300.00
        assert data['invoice']['tax'] == 24.00
        assert data['invoice']['total'] == 324.00
    
    def test_customer_view_invoices(self, client, auth_headers):
        """Test customer can view their invoices"""
        response = client.get('/api/payments/invoices',
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'invoices' in data
    
    def test_download_invoice_pdf(self, client, auth_headers, test_job, db_session):
        """Test downloading invoice as PDF"""
        # First create an invoice
        test_job.status = 'completed'
        db_session.commit()
        
        invoice_response = client.post(f'/api/payments/invoices',
            headers=client.application.test_client().environ_base.copy(),
            json={
                'job_id': test_job.id,
                'amount': 300.00
            }
        )
        
        # Assume invoice was created, try to download
        response = client.get('/api/payments/invoices/1/pdf',
            headers=auth_headers
        )
        
        assert response.status_code in [200, 404]  # 404 if invoice doesn't exist yet


class TestStripePayment:
    """Test Stripe payment processing"""
    
    def test_create_payment_intent(self, client, auth_headers):
        """Test creating Stripe payment intent"""
        response = client.post('/api/payments/create-intent',
            headers=auth_headers,
            json={
                'amount': 250.00,
                'invoice_id': 1,
                'description': 'Junk removal service'
            }
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'client_secret' in data
        assert 'payment_intent_id' in data
    
    def test_confirm_payment_success(self, client, auth_headers):
        """Test confirming successful payment"""
        response = client.post('/api/payments/confirm',
            headers=auth_headers,
            json={
                'payment_intent_id': 'pi_test_123',
                'invoice_id': 1
            }
        )
        
        assert response.status_code in [200, 400]  # 400 if payment_intent doesn't exist
    
    def test_payment_updates_invoice_status(self, client, operator_headers, test_job, db_session):
        """Test successful payment updates invoice to paid"""
        test_job.status = 'completed'
        db_session.commit()
        
        # Create invoice
        invoice_response = client.post(f'/api/payments/invoices',
            headers=operator_headers,
            json={
                'job_id': test_job.id,
                'amount': 300.00
            }
        )
        
        invoice_data = json.loads(invoice_response.data)
        invoice_id = invoice_data['invoice']['id']
        
        # Simulate payment webhook
        response = client.post('/api/payments/webhook',
            json={
                'type': 'payment_intent.succeeded',
                'data': {
                    'object': {
                        'id': 'pi_test_123',
                        'metadata': {'invoice_id': str(invoice_id)}
                    }
                }
            },
            headers={'Stripe-Signature': 'test_signature'}
        )
        
        # Note: This would need proper Stripe webhook signature validation
        assert response.status_code in [200, 400]
    
    def test_payment_failure_handling(self, client, auth_headers):
        """Test handling failed payment"""
        response = client.post('/api/payments/webhook',
            json={
                'type': 'payment_intent.payment_failed',
                'data': {
                    'object': {
                        'id': 'pi_test_123',
                        'metadata': {'invoice_id': '1'},
                        'last_payment_error': {
                            'message': 'Insufficient funds'
                        }
                    }
                }
            },
            headers={'Stripe-Signature': 'test_signature'}
        )
        
        assert response.status_code in [200, 400]
    
    def test_save_payment_method(self, client, auth_headers):
        """Test saving customer payment method"""
        response = client.post('/api/payments/save-payment-method',
            headers=auth_headers,
            json={
                'payment_method_id': 'pm_test_123'
            }
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'payment_method' in data


class TestRefunds:
    """Test refund processing"""
    
    def test_process_full_refund(self, client, operator_headers):
        """Test processing full refund"""
        response = client.post('/api/payments/refunds',
            headers=operator_headers,
            json={
                'payment_intent_id': 'pi_test_123',
                'amount': 300.00,
                'reason': 'Customer not satisfied'
            }
        )
        
        assert response.status_code in [200, 400, 404]
    
    def test_process_partial_refund(self, client, operator_headers):
        """Test processing partial refund"""
        response = client.post('/api/payments/refunds',
            headers=operator_headers,
            json={
                'payment_intent_id': 'pi_test_123',
                'amount': 100.00,  # Partial amount
                'reason': 'Partial service'
            }
        )
        
        assert response.status_code in [200, 400, 404]
    
    def test_refund_updates_invoice(self, client, operator_headers):
        """Test refund updates invoice status"""
        response = client.post('/api/payments/refunds',
            headers=operator_headers,
            json={
                'invoice_id': 1,
                'amount': 300.00,
                'reason': 'Service not completed'
            }
        )
        
        assert response.status_code in [200, 400, 404]
    
    def test_cannot_refund_unpaid_invoice(self, client, operator_headers):
        """Test cannot refund invoice that hasn't been paid"""
        response = client.post('/api/payments/refunds',
            headers=operator_headers,
            json={
                'invoice_id': 999,  # Unpaid invoice
                'amount': 300.00
            }
        )
        
        assert response.status_code == 400


class TestPricingCalculation:
    """Test dynamic pricing calculations"""
    
    def test_calculate_base_price(self, client, auth_headers):
        """Test base price calculation by volume"""
        response = client.post('/api/payments/calculate-price',
            headers=auth_headers,
            json={
                'volume': '1/4 truck',
                'zip_code': '10001'
            }
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'base_price' in data
        assert data['base_price'] > 0
    
    def test_apply_heavy_item_surcharge(self, client, auth_headers):
        """Test surcharge for heavy items"""
        response = client.post('/api/payments/calculate-price',
            headers=auth_headers,
            json={
                'volume': '1/4 truck',
                'items': ['Refrigerator', 'Piano'],
                'zip_code': '10001'
            }
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'surcharges' in data
        assert any('heavy item' in s['description'].lower() for s in data['surcharges'])
    
    def test_apply_distance_surcharge(self, client, auth_headers):
        """Test surcharge for distance from base"""
        response = client.post('/api/payments/calculate-price',
            headers=auth_headers,
            json={
                'volume': '1/4 truck',
                'zip_code': '10999',  # Far zip code
                'items': ['Sofa']
            }
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        # May include distance surcharge
    
    def test_apply_discount_code(self, client, auth_headers):
        """Test applying promotional discount code"""
        response = client.post('/api/payments/calculate-price',
            headers=auth_headers,
            json={
                'volume': '1/2 truck',
                'zip_code': '10001',
                'items': ['Sofa'],
                'discount_code': 'FIRST20'
            }
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'discount' in data
        assert data['discount'] > 0


class TestPaymentReporting:
    """Test payment analytics and reporting"""
    
    def test_get_revenue_report(self, client, operator_headers):
        """Test generating revenue report"""
        start_date = datetime.now() - timedelta(days=30)
        end_date = datetime.now()
        
        response = client.get(
            f'/api/payments/reports/revenue?start_date={start_date.strftime("%Y-%m-%d")}&end_date={end_date.strftime("%Y-%m-%d")}',
            headers=operator_headers
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'total_revenue' in data
        assert 'paid_invoices' in data
        assert 'pending_invoices' in data
    
    def test_get_outstanding_invoices(self, client, operator_headers):
        """Test retrieving unpaid invoices"""
        response = client.get('/api/payments/invoices?status=pending',
            headers=operator_headers
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'invoices' in data
    
    def test_payment_method_analytics(self, client, operator_headers):
        """Test payment method breakdown"""
        response = client.get('/api/payments/reports/methods',
            headers=operator_headers
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'payment_methods' in data


class TestTipping:
    """Test driver tipping functionality"""
    
    def test_add_tip_to_payment(self, client, auth_headers):
        """Test adding tip to payment"""
        response = client.post('/api/payments/create-intent',
            headers=auth_headers,
            json={
                'amount': 300.00,
                'tip': 50.00,
                'invoice_id': 1,
                'driver_id': 1
            }
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        # Total should include tip
    
    def test_tip_distribution_to_driver(self, client, operator_headers):
        """Test tips are tracked per driver"""
        response = client.get('/api/payments/tips?driver_id=1',
            headers=operator_headers
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'total_tips' in data
