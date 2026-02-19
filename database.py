import sqlite3
import os
from datetime import datetime
import json

# Try to import PostgreSQL support
try:
    import psycopg2
    import psycopg2.extras
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False


class Database:
    def __init__(self, db_path='umuve.db'):
        # Check if DATABASE_URL is set (for PostgreSQL)
        self.database_url = os.environ.get('DATABASE_URL')
        
        if self.database_url and HAS_POSTGRES:
            self.db_type = 'postgres'
            # Fix postgres:// to postgresql:// for psycopg2
            if self.database_url.startswith('postgres://'):
                self.database_url = self.database_url.replace('postgres://', 'postgresql://', 1)
            print(f"Using PostgreSQL database")
        else:
            self.db_type = 'sqlite'
            self.db_path = db_path
            print(f"Using SQLite database: {db_path}")
        
        self.init_db()
    
    def get_connection(self):
        if self.db_type == 'postgres':
            return psycopg2.connect(self.database_url)
        else:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            return conn
    
    def init_db(self):
        """Initialize database with schema"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if self.db_type == 'postgres':
            # PostgreSQL schema
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS customers (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS services (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    base_price REAL NOT NULL,
                    unit TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bookings (
                    id SERIAL PRIMARY KEY,
                    customer_id INTEGER NOT NULL,
                    address TEXT NOT NULL,
                    zip_code TEXT NOT NULL,
                    services TEXT NOT NULL,
                    photos TEXT,
                    scheduled_datetime TEXT NOT NULL,
                    estimated_price REAL NOT NULL,
                    status TEXT DEFAULT 'pending',
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (customer_id) REFERENCES customers(id)
                )
            ''')
            
            # Check if services table is empty
            cursor.execute('SELECT COUNT(*) FROM services')
            count = cursor.fetchone()[0]
        else:
            # SQLite schema
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS customers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS services (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    base_price REAL NOT NULL,
                    unit TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bookings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id INTEGER NOT NULL,
                    address TEXT NOT NULL,
                    zip_code TEXT NOT NULL,
                    services TEXT NOT NULL,
                    photos TEXT,
                    scheduled_datetime TEXT NOT NULL,
                    estimated_price REAL NOT NULL,
                    status TEXT DEFAULT 'pending',
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (customer_id) REFERENCES customers(id)
                )
            ''')
            
            cursor.execute('SELECT COUNT(*) FROM services')
            count = cursor.fetchone()[0]
        
        # Seed services if empty
        if count == 0:
            services = [
                ('Single Item Removal', 'Remove one large item (couch, mattress, appliance)', 89.00, 'item'),
                ('Small Load', 'Up to 4 cubic yards - fits in pickup bed', 150.00, 'load'),
                ('Medium Load', '4-8 cubic yards - small trailer', 250.00, 'load'),
                ('Large Load', '8-12 cubic yards - large trailer', 400.00, 'load'),
                ('Full Truck', '12-16 cubic yards - full truck', 550.00, 'load'),
                ('Appliance Removal', 'Refrigerator, washer, dryer, etc.', 75.00, 'item'),
                ('Furniture Removal', 'Couch, bed, table, etc.', 65.00, 'item'),
                ('Electronics Disposal', 'TV, computer, printer, etc.', 50.00, 'item'),
                ('Yard Waste', 'Branches, leaves, lawn debris', 100.00, 'load'),
                ('Construction Debris', 'Drywall, lumber, tiles, etc.', 200.00, 'load'),
            ]
            
            if self.db_type == 'postgres':
                cursor.executemany('''
                    INSERT INTO services (name, description, base_price, unit)
                    VALUES (%s, %s, %s, %s)
                ''', services)
            else:
                cursor.executemany('''
                    INSERT INTO services (name, description, base_price, unit)
                    VALUES (?, ?, ?, ?)
                ''', services)
        
        conn.commit()
        conn.close()
    
    # Customer methods
    def create_customer(self, name, email, phone):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if self.db_type == 'postgres':
            cursor.execute('''
                INSERT INTO customers (name, email, phone)
                VALUES (%s, %s, %s)
                RETURNING id
            ''', (name, email, phone))
            customer_id = cursor.fetchone()[0]
        else:
            cursor.execute('''
                INSERT INTO customers (name, email, phone)
                VALUES (?, ?, ?)
            ''', (name, email, phone))
            customer_id = cursor.lastrowid
        
        conn.commit()
        conn.close()
        return customer_id
    
    def get_customer(self, customer_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if self.db_type == 'postgres':
            cursor.execute('SELECT * FROM customers WHERE id = %s', (customer_id,))
            customer = cursor.fetchone()
            conn.close()
            if customer:
                return {
                    'id': customer[0],
                    'name': customer[1],
                    'email': customer[2],
                    'phone': customer[3],
                    'created_at': customer[4]
                }
        else:
            cursor.execute('SELECT * FROM customers WHERE id = ?', (customer_id,))
            customer = cursor.fetchone()
            conn.close()
            return dict(customer) if customer else None
        
        return None
    
    # Service methods
    def get_services(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM services ORDER BY base_price')
        
        if self.db_type == 'postgres':
            services = []
            for row in cursor.fetchall():
                services.append({
                    'id': row[0],
                    'name': row[1],
                    'description': row[2],
                    'base_price': row[3],
                    'unit': row[4],
                    'created_at': row[5]
                })
        else:
            services = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        return services
    
    def get_service(self, service_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if self.db_type == 'postgres':
            cursor.execute('SELECT * FROM services WHERE id = %s', (service_id,))
            service = cursor.fetchone()
            conn.close()
            if service:
                return {
                    'id': service[0],
                    'name': service[1],
                    'description': service[2],
                    'base_price': service[3],
                    'unit': service[4],
                    'created_at': service[5]
                }
        else:
            cursor.execute('SELECT * FROM services WHERE id = ?', (service_id,))
            service = cursor.fetchone()
            conn.close()
            return dict(service) if service else None
        
        return None
    
    # Booking methods
    def create_booking(self, customer_id, address, zip_code, services, photos, scheduled_datetime, estimated_price, notes=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if self.db_type == 'postgres':
            cursor.execute('''
                INSERT INTO bookings (customer_id, address, zip_code, services, photos, scheduled_datetime, estimated_price, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            ''', (customer_id, address, zip_code, json.dumps(services), json.dumps(photos), scheduled_datetime, estimated_price, notes))
            booking_id = cursor.fetchone()[0]
        else:
            cursor.execute('''
                INSERT INTO bookings (customer_id, address, zip_code, services, photos, scheduled_datetime, estimated_price, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (customer_id, address, zip_code, json.dumps(services), json.dumps(photos), scheduled_datetime, estimated_price, notes))
            booking_id = cursor.lastrowid
        
        conn.commit()
        conn.close()
        return booking_id
    
    def get_booking(self, booking_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if self.db_type == 'postgres':
            cursor.execute('''
                SELECT b.*, c.name as customer_name, c.email as customer_email, c.phone as customer_phone
                FROM bookings b
                JOIN customers c ON b.customer_id = c.id
                WHERE b.id = %s
            ''', (booking_id,))
            booking = cursor.fetchone()
            conn.close()
            
            if booking:
                return {
                    'id': booking[0],
                    'customer_id': booking[1],
                    'address': booking[2],
                    'zip_code': booking[3],
                    'services': json.loads(booking[4]),
                    'photos': json.loads(booking[5]) if booking[5] else [],
                    'scheduled_datetime': booking[6],
                    'estimated_price': booking[7],
                    'status': booking[8],
                    'notes': booking[9],
                    'created_at': booking[10],
                    'customer_name': booking[11],
                    'customer_email': booking[12],
                    'customer_phone': booking[13]
                }
        else:
            cursor.execute('''
                SELECT b.*, c.name as customer_name, c.email as customer_email, c.phone as customer_phone
                FROM bookings b
                JOIN customers c ON b.customer_id = c.id
                WHERE b.id = ?
            ''', (booking_id,))
            booking = cursor.fetchone()
            conn.close()
            
            if booking:
                booking_dict = dict(booking)
                booking_dict['services'] = json.loads(booking_dict['services'])
                booking_dict['photos'] = json.loads(booking_dict['photos']) if booking_dict['photos'] else []
                return booking_dict
        
        return None
    
    def update_booking_status(self, booking_id, status):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if self.db_type == 'postgres':
            cursor.execute('UPDATE bookings SET status = %s WHERE id = %s', (status, booking_id))
        else:
            cursor.execute('UPDATE bookings SET status = ? WHERE id = ?', (status, booking_id))
        
        conn.commit()
        conn.close()
