from flask import Blueprint, request, jsonify
from app import db
from app.models import Invoice, Payment, Customer
from app.utils import require_auth, require_role, serialize_model, paginate_query
from datetime import datetime

payments_bp = Blueprint('payments', __name__)


@payments_bp.route('/invoices', methods=['GET'])
@require_auth
def list_invoices():
    """
    List invoices for the tenant
    GET /api/payments/invoices?page=1&per_page=20&status=sent&customer_id=uuid
    """
    tenant_id = request.tenant_id
    
    # Build query with tenant isolation
    query = Invoice.query.filter_by(tenant_id=tenant_id, deleted_at=None)
    
    # Apply filters
    status = request.args.get('status')
    if status:
        query = query.filter_by(status=status)
    
    customer_id = request.args.get('customer_id')
    if customer_id:
        query = query.filter_by(customer_id=customer_id)
    
    # Order by invoice date (newest first)
    query = query.order_by(Invoice.invoice_date.desc())
    
    # Pagination
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    result = paginate_query(query, page, per_page)
    
    # Serialize items
    result['items'] = [serialize_model(invoice) for invoice in result['items']]
    
    return jsonify(result), 200


@payments_bp.route('/invoices/<invoice_id>', methods=['GET'])
@require_auth
def get_invoice(invoice_id):
    """Get a specific invoice by ID"""
    tenant_id = request.tenant_id
    
    invoice = Invoice.query.filter_by(
        id=invoice_id,
        tenant_id=tenant_id,
        deleted_at=None
    ).first()
    
    if not invoice:
        return jsonify({'error': 'Invoice not found'}), 404
    
    return jsonify(serialize_model(invoice)), 200


@payments_bp.route('', methods=['GET'])
@require_auth
def list_payments():
    """
    List payments for the tenant
    GET /api/payments?page=1&per_page=20&status=completed&invoice_id=uuid
    """
    tenant_id = request.tenant_id
    
    # Build query with tenant isolation
    query = Payment.query.filter_by(tenant_id=tenant_id)
    
    # Apply filters
    status = request.args.get('payment_status')
    if status:
        query = query.filter_by(payment_status=status)
    
    invoice_id = request.args.get('invoice_id')
    if invoice_id:
        query = query.filter_by(invoice_id=invoice_id)
    
    customer_id = request.args.get('customer_id')
    if customer_id:
        query = query.filter_by(customer_id=customer_id)
    
    # Order by payment date (newest first)
    query = query.order_by(Payment.payment_date.desc())
    
    # Pagination
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    result = paginate_query(query, page, per_page)
    
    # Serialize items
    result['items'] = [serialize_model(payment) for payment in result['items']]
    
    return jsonify(result), 200


@payments_bp.route('', methods=['POST'])
@require_auth
@require_role('admin', 'dispatcher')
def record_payment():
    """
    Record a payment
    POST /api/payments
    Body: {
        "invoice_id": "uuid",
        "customer_id": "uuid",
        "amount": 150.00,
        "payment_method": "credit_card",
        "payment_status": "completed",
        "transaction_id": "txn_123456",
        "processor": "stripe",
        "reference_number": "1234",
        "notes": "Payment notes"
    }
    """
    tenant_id = request.tenant_id
    data = request.get_json()
    
    # Validate required fields
    required_fields = ['invoice_id', 'customer_id', 'amount', 'payment_method', 'payment_status']
    if not all(field in data for field in required_fields):
        return jsonify({'error': 'Missing required fields'}), 400
    
    # Verify invoice belongs to tenant
    invoice = Invoice.query.filter_by(
        id=data['invoice_id'],
        tenant_id=tenant_id,
        deleted_at=None
    ).first()
    
    if not invoice:
        return jsonify({'error': 'Invalid invoice'}), 400
    
    # Verify customer belongs to tenant
    customer = Customer.query.filter_by(
        id=data['customer_id'],
        tenant_id=tenant_id,
        deleted_at=None
    ).first()
    
    if not customer:
        return jsonify({'error': 'Invalid customer'}), 400
    
    # Validate amount
    try:
        amount = float(data['amount'])
        if amount <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid amount'}), 400
    
    # Create payment
    payment = Payment(
        tenant_id=tenant_id,
        invoice_id=data['invoice_id'],
        customer_id=data['customer_id'],
        payment_method=data['payment_method'],
        payment_status=data['payment_status'],
        amount=amount,
        transaction_id=data.get('transaction_id'),
        processor=data.get('processor'),
        reference_number=data.get('reference_number'),
        notes=data.get('notes'),
        processor_response=data.get('processor_response')
    )
    
    try:
        db.session.add(payment)
        
        # Update invoice amounts if payment is completed
        if data['payment_status'] == 'completed':
            invoice.amount_paid = float(invoice.amount_paid or 0) + amount
            invoice.amount_due = float(invoice.total_amount) - float(invoice.amount_paid)
            
            # Update invoice status
            if invoice.amount_due <= 0:
                invoice.status = 'paid'
                invoice.paid_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'message': 'Payment recorded successfully',
            'payment': serialize_model(payment)
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'Failed to record payment', 'details': str(e)}), 500
