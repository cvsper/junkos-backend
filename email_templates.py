"""
Professional HTML email templates for Umuve.

Every public function returns a complete HTML string ready for sending via
the ``send_email`` helper in ``notifications.py``.

Design tokens:
  - Primary accent: #DC2626 (red)
  - Background:     #fafaf8 (warm off-white)
  - Card:           #ffffff
  - Text dark:      #111827
  - Text muted:     #4b5563 / #6b7280
  - Font stack:     Outfit, DM Sans, Arial, sans-serif

All styles are inlined for maximum email-client compatibility.  No external
resources (fonts, images, scripts) are referenced.
"""

from html import escape as _esc


# ---------------------------------------------------------------------------
# Shared layout helpers
# ---------------------------------------------------------------------------

def _header():
    """Umuve branded header block."""
    return (
        '<div style="text-align:center;margin-bottom:30px;">'
        '<h1 style="color:#DC2626;font-size:28px;margin:0;font-family:\'Outfit\',\'DM Sans\',Arial,sans-serif;font-weight:700;letter-spacing:-0.5px;">Umuve</h1>'
        '<p style="color:#6b7280;margin:5px 0 0;font-size:14px;">Premium Junk Removal</p>'
        '</div>'
    )


def _footer():
    """Umuve footer with company address."""
    return (
        '<div style="text-align:center;margin-top:30px;padding-top:20px;border-top:1px solid #e5e7eb;color:#9ca3af;font-size:12px;line-height:1.6;">'
        '<p style="margin:0 0 4px;">Umuve &mdash; South Florida\'s Premium Junk Removal</p>'
        '<p style="margin:0 0 4px;">Palm Beach &amp; Broward County, FL</p>'
        '<p style="margin:0;">(561) 888-3427 &middot; support@goumuve.com</p>'
        '</div>'
    )


def _wrap(body_html):
    """Wrap inner content in the common email shell (background, card, header, footer)."""
    return (
        '<!DOCTYPE html>'
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1.0">'
        '<title>Umuve</title></head>'
        '<body style="margin:0;padding:0;background-color:#f3f4f6;-webkit-text-size-adjust:100%;">'
        '<div style="font-family:\'Outfit\',\'DM Sans\',Arial,sans-serif;max-width:600px;margin:0 auto;background:#fafaf8;padding:40px 20px;">'
        + _header()
        + '<div style="background:#ffffff;border-radius:12px;padding:30px;box-shadow:0 1px 3px rgba(0,0,0,0.1);">'
        + body_html
        + '</div>'
        + _footer()
        + '</div></body></html>'
    )


def _detail_row(label, value, is_last=False):
    """Single key-value row for detail tables."""
    border = 'border-top:1px solid #FECACA;' if is_last else ''
    pad_top = '12px' if is_last else '8px'
    val_color = '#DC2626' if is_last else '#111827'
    val_size = '20px' if is_last else '14px'
    val_weight = '700' if is_last else '600'
    return (
        '<tr style="{border}">'
        '<td style="padding:{pt} 0 8px;color:#6b7280;font-size:14px;">{label}</td>'
        '<td style="padding:{pt} 0 8px;color:{vc};font-size:{vs};font-weight:{vw};text-align:right;">{value}</td>'
        '</tr>'
    ).format(border=border, pt=pad_top, label=_esc(str(label)),
             value=_esc(str(value)), vc=val_color, vs=val_size, vw=val_weight)


def _detail_table(rows):
    """Red-tinted detail box.  *rows* is a list of (label, value) tuples."""
    inner = ''
    for i, (label, value) in enumerate(rows):
        inner += _detail_row(label, value, is_last=(i == len(rows) - 1))
    return (
        '<div style="background:#FEF2F2;border:1px solid #FECACA;border-radius:8px;padding:20px;margin:20px 0;">'
        '<table style="width:100%;border-collapse:collapse;">'
        + inner
        + '</table></div>'
    )


def _button(url, label):
    """Call-to-action button."""
    return (
        '<div style="text-align:center;margin:28px 0 12px;">'
        '<a href="{url}" style="display:inline-block;background:#DC2626;color:#ffffff;'
        'text-decoration:none;padding:14px 36px;border-radius:8px;font-size:16px;'
        'font-weight:600;line-height:1;">'.format(url=_esc(str(url)))
        + _esc(str(label))
        + '</a></div>'
    )


# ---------------------------------------------------------------------------
# 1. Booking confirmation
# ---------------------------------------------------------------------------

def booking_confirmation_html(customer_name, booking_id, address, date, time, total):
    """Return HTML for a booking-confirmed email."""
    name = _esc(str(customer_name)) if customer_name else 'there'
    short_id = str(booking_id)[:8] if booking_id else 'N/A'
    try:
        total_fmt = '${:.2f}'.format(float(total))
    except (TypeError, ValueError):
        total_fmt = '$0.00'

    body = (
        '<h2 style="color:#111827;margin:0 0 12px;font-size:22px;">Booking Confirmed!</h2>'
        '<p style="color:#4b5563;line-height:1.6;">Hi {name},</p>'
        '<p style="color:#4b5563;line-height:1.6;">Your junk removal is scheduled. Here are your details:</p>'
    ).format(name=name)

    body += _detail_table([
        ('Booking ID', '#{}'.format(short_id)),
        ('Address', address or 'TBD'),
        ('Date', date or 'TBD'),
        ('Time', time or 'TBD'),
        ('Total', total_fmt),
    ])

    body += (
        '<p style="color:#4b5563;font-size:14px;line-height:1.6;">'
        'We\'ll send you a reminder 24 hours before your appointment. '
        'Need to reschedule? Reply to this email or call us at '
        '<strong>(561) 888-3427</strong>.</p>'
    )

    return _wrap(body)


# ---------------------------------------------------------------------------
# 2. Driver / crew assigned
# ---------------------------------------------------------------------------

def booking_assigned_html(customer_name, driver_name, truck_type, eta):
    """Return HTML for a driver-assigned notification."""
    name = _esc(str(customer_name)) if customer_name else 'there'
    driver = _esc(str(driver_name)) if driver_name else 'Your driver'

    body = (
        '<h2 style="color:#111827;margin:0 0 12px;font-size:22px;">Your Crew Is Assigned!</h2>'
        '<p style="color:#4b5563;line-height:1.6;">Hi {name},</p>'
        '<p style="color:#4b5563;line-height:1.6;">Great news &mdash; a crew has been assigned to your upcoming pickup.</p>'
    ).format(name=name)

    body += _detail_table([
        ('Driver', driver),
        ('Truck', _esc(str(truck_type)) if truck_type else 'Standard'),
        ('ETA', _esc(str(eta)) if eta else 'TBD'),
    ])

    body += (
        '<p style="color:#4b5563;font-size:14px;line-height:1.6;">'
        'We\'ll notify you again once your driver is en route. '
        'If you have any questions, call us at <strong>(561) 888-3427</strong>.</p>'
    )

    return _wrap(body)


# ---------------------------------------------------------------------------
# 3. Driver en route
# ---------------------------------------------------------------------------

def driver_en_route_html(customer_name, driver_name, eta_minutes):
    """Return HTML for a driver-on-the-way notification."""
    name = _esc(str(customer_name)) if customer_name else 'there'
    driver = _esc(str(driver_name)) if driver_name else 'Your driver'
    try:
        minutes = int(eta_minutes)
    except (TypeError, ValueError):
        minutes = None

    eta_text = '{} minutes'.format(minutes) if minutes else 'shortly'

    body = (
        '<h2 style="color:#111827;margin:0 0 12px;font-size:22px;">Your Driver Is On The Way!</h2>'
        '<p style="color:#4b5563;line-height:1.6;">Hi {name},</p>'
        '<p style="color:#4b5563;line-height:1.6;">'
        '<strong>{driver}</strong> is headed to your location and should arrive in '
        '<strong>{eta}</strong>.</p>'
    ).format(name=name, driver=driver, eta=_esc(eta_text))

    body += (
        '<div style="background:#FEF2F2;border:1px solid #FECACA;border-radius:8px;'
        'padding:24px;margin:20px 0;text-align:center;">'
        '<p style="color:#6b7280;font-size:13px;margin:0 0 6px;text-transform:uppercase;letter-spacing:0.5px;">Estimated Arrival</p>'
        '<p style="color:#DC2626;font-size:36px;font-weight:700;margin:0;">{eta}</p>'
        '</div>'
    ).format(eta=_esc(eta_text))

    body += (
        '<p style="color:#4b5563;font-size:14px;line-height:1.6;">'
        'Please make sure the items are accessible. '
        'If you need to reach your driver, call us at <strong>(561) 888-3427</strong>.</p>'
    )

    return _wrap(body)


# ---------------------------------------------------------------------------
# 4. Job completed
# ---------------------------------------------------------------------------

def job_completed_html(customer_name, booking_id, total, rating_url):
    """Return HTML for a job-completed email with a rating CTA."""
    name = _esc(str(customer_name)) if customer_name else 'there'
    short_id = str(booking_id)[:8] if booking_id else 'N/A'
    try:
        total_fmt = '${:.2f}'.format(float(total))
    except (TypeError, ValueError):
        total_fmt = '$0.00'

    body = (
        '<h2 style="color:#111827;margin:0 0 12px;font-size:22px;">Job Complete!</h2>'
        '<p style="color:#4b5563;line-height:1.6;">Hi {name},</p>'
        '<p style="color:#4b5563;line-height:1.6;">'
        'Your junk removal (Booking <strong>#{id}</strong>) has been completed. '
        'We hope everything went smoothly!</p>'
    ).format(name=name, id=_esc(short_id))

    body += _detail_table([
        ('Booking ID', '#{}'.format(short_id)),
        ('Total Charged', total_fmt),
    ])

    if rating_url:
        body += (
            '<p style="color:#4b5563;font-size:14px;line-height:1.6;text-align:center;">'
            'We\'d love your feedback &mdash; it only takes 30 seconds:</p>'
        )
        body += _button(rating_url, 'Rate Your Experience')

    body += (
        '<p style="color:#6b7280;font-size:13px;line-height:1.6;text-align:center;">'
        'Thank you for choosing Umuve!</p>'
    )

    return _wrap(body)


# ---------------------------------------------------------------------------
# 5. Payment receipt
# ---------------------------------------------------------------------------

def payment_receipt_html(customer_name, booking_id, amount, payment_method_last4, date):
    """Return HTML for a payment receipt."""
    name = _esc(str(customer_name)) if customer_name else 'there'
    short_id = str(booking_id)[:8] if booking_id else 'N/A'
    try:
        amt_fmt = '${:.2f}'.format(float(amount))
    except (TypeError, ValueError):
        amt_fmt = '$0.00'

    last4 = _esc(str(payment_method_last4)) if payment_method_last4 else '****'

    body = (
        '<h2 style="color:#111827;margin:0 0 12px;font-size:22px;">Payment Receipt</h2>'
        '<p style="color:#4b5563;line-height:1.6;">Hi {name},</p>'
        '<p style="color:#4b5563;line-height:1.6;">'
        'Here\'s the receipt for your recent Umuve service.</p>'
    ).format(name=name)

    body += _detail_table([
        ('Booking ID', '#{}'.format(short_id)),
        ('Date', _esc(str(date)) if date else 'N/A'),
        ('Payment Method', 'Card ending in {}'.format(last4)),
        ('Amount Paid', amt_fmt),
    ])

    body += (
        '<p style="color:#6b7280;font-size:13px;line-height:1.6;">'
        'If you have billing questions, reply to this email or call '
        '<strong>(561) 888-3427</strong>.</p>'
    )

    return _wrap(body)


# ---------------------------------------------------------------------------
# 6. Welcome
# ---------------------------------------------------------------------------

def welcome_html(name):
    """Return HTML for a welcome / signup email."""
    display_name = _esc(str(name)) if name else 'there'

    body = (
        '<h2 style="color:#111827;margin:0 0 12px;font-size:22px;">Welcome to Umuve!</h2>'
        '<p style="color:#4b5563;line-height:1.6;">Hi {name},</p>'
        '<p style="color:#4b5563;line-height:1.6;">'
        'Thanks for signing up! We\'re South Florida\'s premium junk removal service, '
        'and we can\'t wait to help you reclaim your space.</p>'
    ).format(name=display_name)

    body += (
        '<div style="background:#FEF2F2;border:1px solid #FECACA;border-radius:8px;'
        'padding:24px;margin:20px 0;">'
        '<h3 style="color:#111827;margin:0 0 12px;font-size:16px;">Here\'s what you can do:</h3>'
        '<ul style="color:#4b5563;padding-left:20px;margin:0;line-height:2;">'
        '<li>Book a pickup in under 2 minutes</li>'
        '<li>Upload photos for an instant estimate</li>'
        '<li>Track your driver in real time</li>'
        '<li>Pay securely online</li>'
        '</ul></div>'
    )

    body += _button('https://goumuve.com/book', 'Book Your First Pickup')

    body += (
        '<p style="color:#6b7280;font-size:13px;line-height:1.6;text-align:center;">'
        'Questions? Just reply to this email or call <strong>(561) 888-3427</strong>.</p>'
    )

    return _wrap(body)


# ---------------------------------------------------------------------------
# 6a. Job status update (generic — covers assigned, en_route, arrived, completed, cancelled)
# ---------------------------------------------------------------------------

_STATUS_HEADLINES = {
    'assigned':  'A Driver Has Been Assigned',
    'accepted':  'Your Driver Has Accepted the Job',
    'en_route':  'Your Driver Is On The Way',
    'arrived':   'Your Driver Has Arrived',
    'started':   'Junk Removal In Progress',
    'completed': 'Your Pickup Is Complete!',
    'cancelled': 'Your Booking Has Been Cancelled',
}

_STATUS_DESCRIPTIONS = {
    'assigned':  'A driver has been assigned to your upcoming pickup and will contact you when it\'s time.',
    'accepted':  'Your driver has confirmed and accepted the job. They\'ll be heading your way soon.',
    'en_route':  'Your driver is on the way to your location. Please make sure items are accessible.',
    'arrived':   'Your driver has arrived at the pickup location. Please meet them if possible.',
    'started':   'The removal is underway! Your driver is loading up the junk right now.',
    'completed': 'All done! Your junk has been hauled away. We hope everything went smoothly.',
    'cancelled': 'This booking has been cancelled. If this was a mistake, please contact us to rebook.',
}

_STATUS_ICONS = {
    'assigned':  '&#x1F69A;',  # truck
    'accepted':  '&#x2705;',   # check
    'en_route':  '&#x1F3CE;',  # racing car
    'arrived':   '&#x1F4CD;',  # pin
    'started':   '&#x1F4AA;',  # bicep
    'completed': '&#x1F389;',  # party popper
    'cancelled': '&#x274C;',   # cross
}


def job_status_update_html(customer_name, job_id, status, driver_name=None):
    """Return HTML for a generic job-status-change email.

    Covers: assigned, accepted, en_route, arrived, started, completed, cancelled.
    """
    name = _esc(str(customer_name)) if customer_name else 'there'
    short_id = str(job_id)[:8] if job_id else 'N/A'
    status_lower = (status or '').lower()

    headline = _STATUS_HEADLINES.get(status_lower, 'Job Status Update')
    description = _STATUS_DESCRIPTIONS.get(status_lower, 'Your job status has been updated to {}.'.format(_esc(status_lower)))
    icon = _STATUS_ICONS.get(status_lower, '&#x1F4E6;')

    body = (
        '<h2 style="color:#111827;margin:0 0 12px;font-size:22px;">{icon} {headline}</h2>'
        '<p style="color:#4b5563;line-height:1.6;">Hi {name},</p>'
        '<p style="color:#4b5563;line-height:1.6;">{desc}</p>'
    ).format(icon=icon, headline=_esc(headline), name=name, desc=description)

    rows = [
        ('Booking ID', '#{}'.format(short_id)),
        ('Status', status_lower.replace('_', ' ').title()),
    ]
    if driver_name:
        rows.insert(1, ('Driver', _esc(str(driver_name))))

    body += _detail_table(rows)

    if status_lower == 'completed':
        body += (
            '<p style="color:#4b5563;font-size:14px;line-height:1.6;text-align:center;">'
            'We\'d love your feedback &mdash; it helps us improve!</p>'
        )
    elif status_lower == 'cancelled':
        body += (
            '<p style="color:#4b5563;font-size:14px;line-height:1.6;">'
            'If you\'d like to rebook, visit our website or call us at '
            '<strong>(561) 888-3427</strong>.</p>'
        )
    else:
        body += (
            '<p style="color:#4b5563;font-size:14px;line-height:1.6;">'
            'Questions? Reply to this email or call <strong>(561) 888-3427</strong>.</p>'
        )

    return _wrap(body)


# ---------------------------------------------------------------------------
# 6b. Pickup reminder (24 hours before scheduled pickup)
# ---------------------------------------------------------------------------

def pickup_reminder_html(customer_name, job_id, address, date, time):
    """Return HTML for a 24-hour pickup reminder email."""
    name = _esc(str(customer_name)) if customer_name else 'there'
    short_id = str(job_id)[:8] if job_id else 'N/A'

    body = (
        '<h2 style="color:#111827;margin:0 0 12px;font-size:22px;">&#x23F0; Pickup Reminder</h2>'
        '<p style="color:#4b5563;line-height:1.6;">Hi {name},</p>'
        '<p style="color:#4b5563;line-height:1.6;">'
        'Just a friendly reminder that your junk removal pickup is '
        '<strong>tomorrow</strong>! Here are the details:</p>'
    ).format(name=name)

    body += _detail_table([
        ('Booking ID', '#{}'.format(short_id)),
        ('Address', _esc(str(address)) if address else 'TBD'),
        ('Date', _esc(str(date)) if date else 'TBD'),
        ('Time', _esc(str(time)) if time else 'TBD'),
    ])

    body += (
        '<div style="background:#fffbeb;border:1px solid #fde68a;border-radius:8px;'
        'padding:16px;margin:20px 0;">'
        '<p style="color:#92400e;margin:0;font-size:14px;line-height:1.6;">'
        '<strong>Preparation tips:</strong></p>'
        '<ul style="color:#92400e;padding-left:20px;margin:8px 0 0;font-size:13px;line-height:1.8;">'
        '<li>Make sure all items are accessible and easy to reach</li>'
        '<li>Clear a path from the items to the nearest door or garage</li>'
        '<li>Disconnect any appliances ahead of time</li>'
        '<li>Move vehicles if the items are in the garage or driveway</li>'
        '</ul></div>'
    )

    body += (
        '<p style="color:#4b5563;font-size:14px;line-height:1.6;">'
        'Need to reschedule? Call us at <strong>(561) 888-3427</strong> '
        'or reply to this email as soon as possible.</p>'
    )

    return _wrap(body)


# ---------------------------------------------------------------------------
# 7. Password reset
# ---------------------------------------------------------------------------

def password_reset_html(name, reset_url):
    """Return HTML for a password-reset email with a clickable link."""
    display_name = _esc(str(name)) if name else 'there'

    body = (
        '<h2 style="color:#111827;margin:0 0 12px;font-size:22px;">Reset Your Password</h2>'
        '<p style="color:#4b5563;line-height:1.6;">Hi {name},</p>'
        '<p style="color:#4b5563;line-height:1.6;">'
        'We received a request to reset your Umuve password. '
        'Click the button below to choose a new one:</p>'
    ).format(name=display_name)

    body += _button(reset_url or '#', 'Reset Password')

    body += (
        '<p style="color:#6b7280;font-size:13px;line-height:1.6;">'
        'This link expires in <strong>1 hour</strong>. '
        'If you didn\'t request a password reset, you can safely ignore this email.</p>'
    )

    body += (
        '<p style="color:#9ca3af;font-size:12px;line-height:1.6;word-break:break-all;">'
        'If the button doesn\'t work, copy and paste this URL into your browser:<br>'
        '<a href="{url}" style="color:#DC2626;">{url}</a></p>'
    ).format(url=_esc(str(reset_url or '')))

    return _wrap(body)
