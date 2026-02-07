"""
Helper utilities
"""
import uuid
from datetime import datetime, date
from decimal import Decimal


def generate_unique_id():
    """
    Generate a unique UUID
    
    Returns:
        str: UUID string
    """
    return str(uuid.uuid4())


def format_currency(amount, currency='USD'):
    """
    Format amount as currency
    
    Args:
        amount: Numeric amount
        currency (str): Currency code
        
    Returns:
        str: Formatted currency string
    """
    if isinstance(amount, (Decimal, float, int)):
        amount = float(amount)
        
        if currency == 'USD':
            return f'${amount:,.2f}'
        else:
            return f'{amount:,.2f} {currency}'
    
    return str(amount)


def format_date(dt, format='%Y-%m-%d'):
    """
    Format date or datetime object
    
    Args:
        dt: datetime or date object
        format (str): strftime format string
        
    Returns:
        str: Formatted date string
    """
    if isinstance(dt, (datetime, date)):
        return dt.strftime(format)
    
    return str(dt)


def parse_date(date_string, format='%Y-%m-%d'):
    """
    Parse date string to date object
    
    Args:
        date_string (str): Date string
        format (str): strptime format string
        
    Returns:
        date: Date object or None if invalid
    """
    try:
        return datetime.strptime(date_string, format).date()
    except (ValueError, TypeError):
        return None


def truncate_string(text, max_length=100, suffix='...'):
    """
    Truncate string to max length
    
    Args:
        text (str): Text to truncate
        max_length (int): Maximum length
        suffix (str): Suffix to add if truncated
        
    Returns:
        str: Truncated string
    """
    if not text or len(text) <= max_length:
        return text
    
    return text[:max_length - len(suffix)] + suffix


def safe_float(value, default=0.0):
    """
    Safely convert value to float
    
    Args:
        value: Value to convert
        default (float): Default value if conversion fails
        
    Returns:
        float: Converted value or default
    """
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_int(value, default=0):
    """
    Safely convert value to int
    
    Args:
        value: Value to convert
        default (int): Default value if conversion fails
        
    Returns:
        int: Converted value or default
    """
    try:
        return int(value)
    except (ValueError, TypeError):
        return default
