"""
Payments blueprint
Handles invoices and payment processing
"""
from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.invoice import Invoice, InvoiceLineItem
from app.models.payment import Payment
from app.models.job import Job
from app.middleware.tenant import tenant_required, get_current_tenant_id
from datetime import datetime, timedelta

payments_bp = Blueprint('payments', __name__)


@payments_bp.route('/invoices', methods=['POST'])
@tenant_required
@login_required
def create_invoice():
    """
    Create a new invoice
    
    POST /api/payments/invoices
    Body: {
        "customer_id": "uuid",
        "job_id": "uuid" (optional),
        "line_items": [
            {
                "description": "Junk removal service",
                "quantity": 1,
                "unit_price": 200.00
            }
        ],
        "tax_rate": 0.0625,
        "dump_fee": 50.00,
        "due_days": 30
    }
    """
    data = request.get_json()
    tenant_id = get_current_tenant_id()
    
    customer_id = data.get('customer_id')
    line_items_data = data.get('line_items', [])
    
    if not customer_id or not line_items_data:
        return jsonify({'error': 'customer_id and line_items required'}), 400
    
    # Generate invoice number
    year = datetime.now().year
    count = Invoice.query.filter(
        Invoice.tenant_id == tenant_id,
        db.extract('year', Invoice.created_at) == year
    ).count() + 1
    invoice_number = f'INV-{year}-{count:04d}'
    
    # Calculate dates
    invoice_date = datetime.now().date()
    due_days = data.get('due_days', 30)
    due_date = invoice_date + timedelta(days=due_days)
    
    # Create invoice
    invoice = Invoice(
        tenant_id=tenant_id,
        customer_id=customer_id,
        job_id=data.get('job_id'),
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        due_date=due_date,
        status='draft',
        subtotal=0,
        tax_amount=0,
        dump_fee=data.get('dump_fee', 0),
        discount_amount=data.get('discount_amount', 0),
        total_amount=0,
        amount_due=0
    )
    
    db.session.add(invoice)
    db.session.flush()
    
    # Add line items
    for item_data in line_items_data:
        if not item_data.get('description') or not item_data.get('unit_price'):
            continue
        
        invoice.add_line_item(
            description=item_data['description'],
            quantity=item_data.get('quantity', 1),
            unit_price=item_data['unit_price']
        )
    
    # Calculate totals
    invoice.recalculate_totals()
    
    # Apply tax if provided
    tax_rate = data.get('tax_rate')
    if tax_rate:
        invoice.tax_amount = invoice.subtotal * float(tax_rate)
        invoice.total_amount += invoice.tax_amount
        invoice.amount_due = invoice.total_amount
    
    db.session.commit()
    
    return jsonify({
        'message': 'Invoice created successfully',
        'invoice': invoice.to_dict()
    }), 201


@payments_bp.route('/invoices', methods=['GET'])
@tenant_required
@login_required
def list_invoices():
    """
    List invoices with filtering
    
    GET /api/payments/invoices?status=sent&customer_id=<uuid>&page=1&per_page=20
    """
    tenant_id = get_current_tenant_id()
    
    query = Invoice.for_tenant(tenant_id)
    
    # Apply filters
    status = request.args.get('status')
    if status:
        query = query.filter(Invoice.status == status)
    
    customer_id = request.args.get('customer_id')
    if customer_id:
        query = query.filter(Invoice.customer_id == customer_id)
    
    # Pagination
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)
    
    pagination = query.order_by(Invoice.invoice_date.desc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )
    
    return jsonify({
        'invoices': [inv.to_dict() for inv in pagination.items],
        'total': pagination.total,
        'page': page,
        'per_page': per_page,
        'pages': pagination.pages
    }), 200


@payments_bp.route('/invoices/<invoice_id>', methods=['GET'])
@tenant_required
@login_required
def get_invoice(invoice_id):
    """
    Get invoice details
    
    GET /api/payments/invoices/<invoice_id>
    """
    tenant_id = get_current_tenant_id()
    
    invoice = Invoice.for_tenant(tenant_id).filter_by(id=invoice_id).first()
    
    if not invoice:
        return jsonify({'error': 'Invoice not found'}), 404
    
    # Include line items
    data = invoice.to_dict()
    data['line_items'] = [item.to_dict() for item in invoice.line_items]
    
    return jsonify({
        'invoice': data
    }), 200


@payments_bp.route('/invoices/<invoice_id>/send', methods=['POST'])
@tenant_required
@login_required
def send_invoice(invoice_id):
    """
    Send invoice to customer
    
    POST /api/payments/invoices/<invoice_id>/send
    """
    tenant_id = get_current_tenant_id()
    
    invoice = Invoice.for_tenant(tenant_id).filter_by(id=invoice_id).first()
    
    if not invoice:
        return jsonify({'error': 'Invoice not found'}), 404
    
    if invoice.status == 'paid':
        return jsonify({'error': 'Invoice already paid'}), 400
    
    invoice.status = 'sent'
    db.session.commit()
    
    # TODO: Send email notification to customer
    
    return jsonify({
        'message': 'Invoice sent successfully',
        'invoice': invoice.to_dict()
    }), 200


@payments_bp.route('/payments', methods=['POST'])
@tenant_required
@login_required
def create_payment():
    """
    Record a payment
    
    POST /api/payments
    Body: {
        "invoice_id": "uuid",
        "payment_method": "credit_card",
        "amount": 250.00,
        "reference_number": "1234",
        "notes": "Payment via Stripe"
    }
    """
    data = request.get_json()
    tenant_id = get_current_tenant_id()
    
    invoice_id = data.get('invoice_id')
    payment_method = data.get('payment_method')
    amount = data.get('amount')
    
    if not invoice_id or not payment_method or not amount:
        return jsonify({'error': 'invoice_id, payment_method, and amount required'}), 400
    
    # Validate invoice
    invoice = Invoice.for_tenant(tenant_id).filter_by(id=invoice_id).first()
    if not invoice:
        return jsonify({'error': 'Invoice not found'}), 404
    
    try:
        amount = float(amount)
        if amount <= 0:
            raise ValueError()
    except (ValueError, TypeError):
        return jsonify({'error': 'amount must be a positive number'}), 400
    
    if amount > invoice.amount_due:
        return jsonify({'error': 'Payment amount exceeds amount due'}), 400
    
    # Create payment
    payment = Payment(
        tenant_id=tenant_id,
        invoice_id=invoice.id,
        customer_id=invoice.customer_id,
        payment_method=payment_method,
        amount=amount,
        reference_number=data.get('reference_number'),
        notes=data.get('notes'),
        payment_date=datetime.utcnow()
    )
    
    db.session.add(payment)
    
    # Process payment (updates invoice)
    payment.process_payment()
    
    # Update customer total spent
    invoice.customer.total_spent += amount
    
    db.session.commit()
    
    return jsonify({
        'message': 'Payment recorded successfully',
        'payment': payment.to_dict(),
        'invoice': invoice.to_dict()
    }), 201


@payments_bp.route('/payments', methods=['GET'])
@tenant_required
@login_required
def list_payments():
    """
    List payments with filtering
    
    GET /api/payments?customer_id=<uuid>&status=completed&page=1
    """
    tenant_id = get_current_tenant_id()
    
    query = Payment.for_tenant(tenant_id)
    
    # Apply filters
    customer_id = request.args.get('customer_id')
    if customer_id:
        query = query.filter(Payment.customer_id == customer_id)
    
    status = request.args.get('status')
    if status:
        query = query.filter(Payment.payment_status == status)
    
    # Pagination
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)
    
    pagination = query.order_by(Payment.payment_date.desc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )
    
    return jsonify({
        'payments': [payment.to_dict() for payment in pagination.items],
        'total': pagination.total,
        'page': page,
        'per_page': per_page,
        'pages': pagination.pages
    }), 200
