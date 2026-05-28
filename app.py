from flask import Flask, request, jsonify
from flask_cors import CORS
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import random
from supabase import create_client, Client
import os
import sqlite3

app = Flask(__name__)
CORS(app)

# --- LOCAL SQLITE PERSISTENT STORAGE FALLBACK LAYER ---
class LocalSQLiteDB:
    def __init__(self, db_path=None):
        if db_path is None:
            db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'aeroassist.db')
        self.db_path = db_path
        self.init_db()

    def get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        conn = self.get_conn()
        cursor = conn.cursor()
        
        # users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                email TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                password TEXT NOT NULL,
                mobile TEXT
            )
        """)
        
        # vendors table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS vendors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                terminal TEXT NOT NULL,
                gate TEXT NOT NULL,
                rating REAL DEFAULT 5.0,
                image_url TEXT,
                availability TEXT DEFAULT 'Available'
            )
        """)
        
        # products table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_id INTEGER,
                name TEXT NOT NULL,
                price REAL NOT NULL,
                rating REAL DEFAULT 5.0,
                image_url TEXT,
                category TEXT NOT NULL,
                description TEXT,
                FOREIGN KEY (vendor_id) REFERENCES vendors(id) ON DELETE CASCADE
            )
        """)
        
        # orders table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL,
                vendor_id INTEGER,
                terminal TEXT NOT NULL,
                gate TEXT NOT NULL,
                status TEXT DEFAULT 'Pending',
                total_price REAL NOT NULL,
                payment_method TEXT DEFAULT 'COD',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (vendor_id) REFERENCES vendors(id) ON DELETE CASCADE
            )
        """)
        
        try:
            cursor.execute("ALTER TABLE orders ADD COLUMN payment_method TEXT DEFAULT 'COD'")
        except Exception:
            pass
        
        # order_items table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                product_id INTEGER,
                quantity INTEGER NOT NULL,
                price REAL NOT NULL,
                product_name TEXT NOT NULL,
                FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
            )
        """)
        
        # lounge_bookings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lounge_bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL,
                vendor_id INTEGER,
                booking_date TEXT NOT NULL,
                booking_time TEXT NOT NULL,
                slots INTEGER NOT NULL,
                status TEXT DEFAULT 'Pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (vendor_id) REFERENCES vendors(id) ON DELETE CASCADE
            )
        """)

        # parking_bookings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS parking_bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL,
                zone TEXT NOT NULL,
                hours INTEGER NOT NULL,
                plate_number TEXT NOT NULL,
                payment_method TEXT NOT NULL,
                total_price REAL NOT NULL,
                status TEXT DEFAULT 'Pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # lost_items table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lost_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                location TEXT NOT NULL,
                contact TEXT NOT NULL,
                type TEXT DEFAULT 'Lost',
                icon TEXT DEFAULT '📦',
                image TEXT DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Schema migration check
        cursor.execute("PRAGMA table_info(lost_items)")
        columns = [row['name'] for row in cursor.fetchall()]
        if 'type' not in columns:
            cursor.execute("ALTER TABLE lost_items ADD COLUMN type TEXT DEFAULT 'Lost'")
            conn.commit()
        if 'image' not in columns:
            cursor.execute("ALTER TABLE lost_items ADD COLUMN image TEXT DEFAULT NULL")
            conn.commit()
        
        cursor.execute("SELECT COUNT(*) FROM lost_items")
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
                INSERT INTO lost_items (name, description, location, contact, type, icon) VALUES
                ('iPhone 13 Pro', 'Blue case', 'Gate 14', '+1234567890', 'Lost', '📱'),
                ('Leather Wallet', 'Brown', 'Terminal 2', '+1234567890', 'Lost', '👛'),
                ('MacBook Air', 'Silver', 'Food Court', '+1234567890', 'Lost', '💻'),
                ('Spectacles', 'RayBan', 'Lounge 1', '+1234567890', 'Lost', '👓')
            """)
            conn.commit()

        # chat_history table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                user_type TEXT NOT NULL,
                session_id INTEGER,
                message TEXT NOT NULL,
                is_user BOOLEAN NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # guides table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS guides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL
            )
        """)
        conn.commit()

        # Seed guides if empty
        cursor.execute("SELECT COUNT(*) FROM guides")
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
                INSERT INTO guides (key, title, content) VALUES
                ('terminal_1', 'Terminal 1', 'Terminal 1 primarily handles domestic operations. It consists of three levels:

• Level 1: Arrivals and Baggage Claim.
• Level 2: Departures and Security Check.
• Level 3: Lounges and Food Court.

Gates A1 to A20 are located in this terminal. Walking time from security to the farthest gate is approximately 12 minutes.'),
                ('terminal_2', 'Terminal 2', 'Terminal 2 is the main hub for international flights. It features state-of-the-art architecture and premium services.

• Level 1: Ground Transportation & International Arrivals.
• Level 2: Duty-Free Shopping & Boarding Gates.
• Level 3: Premium Lounges & Fine Dining.

Gates B1 to B50 are located here. Automated People Movers (APM) connect different zones within the terminal.'),
                ('transfer_guide', 'Inter-Terminal Transfers', '• Free Shuttle Bus: Operates every 10 minutes between T1 and T2. Follow signs for "Terminal Shuttle".

• Airside Transfer: If you have a connecting flight, use the airside transfer bus to avoid re-clearing immigration.

• Walking Path: A covered walkway connects T1 and T2 (approx. 15 mins walk).

• Buggy Service: Elderly and disabled passengers can request a buggy at the information desks.

• Luggage: If your bags are not checked through, you must collect them before transferring between terminals.')
            """)
            conn.commit()
        
        conn.commit()
        
        # Seed default vendors if empty
        cursor.execute("SELECT COUNT(*) FROM vendors")
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
                INSERT INTO vendors (email, password, name, type, terminal, gate, rating, image_url, availability) VALUES
                ('bk@airport.com', 'vendor123', 'Burger King', 'restaurant', 'Terminal 1', 'Gate 9', 4.2, 'https://images.unsplash.com/photo-1568901346375-23c9450c58cd?w=500', 'Available'),
                ('starbucks@airport.com', 'vendor123', 'Starbucks Coffee', 'restaurant', 'Terminal 1', 'Gate 14', 4.5, 'https://images.unsplash.com/photo-1544787219-7f47ccb76574?w=500', 'Available'),
                ('greatkabab@airport.com', 'vendor123', 'The Great Kabab Factory', 'restaurant', 'Terminal 2', 'Gate 25', 4.7, 'https://images.unsplash.com/photo-1603360946369-dc9bb6258143?w=500', 'Available'),
                ('plaza@airport.com', 'vendor123', 'Plaza Premium Lounge', 'lounge', 'Terminal 1', 'Near Gate 12', 4.8, 'https://images.unsplash.com/photo-1566073771259-6a8506099945?w=500', 'Available'),
                ('airindia@airport.com', 'vendor123', 'Air India Lounge', 'lounge', 'Terminal 2', 'Near Gate 18', 4.1, 'https://images.unsplash.com/photo-1582719508461-905c673771fd?w=500', 'Available')
            """)
            conn.commit()
            
            # Seed default products
            cursor.execute("SELECT id FROM vendors WHERE email = 'bk@airport.com'")
            bk_id = cursor.fetchone()[0]
            cursor.execute("SELECT id FROM vendors WHERE email = 'starbucks@airport.com'")
            sb_id = cursor.fetchone()[0]
            cursor.execute("SELECT id FROM vendors WHERE email = 'greatkabab@airport.com'")
            gk_id = cursor.fetchone()[0]
            
            cursor.execute("""
                INSERT INTO products (vendor_id, name, price, rating, image_url, category, description) VALUES
                (?, 'Whopper Burger', 299.00, 4.5, 'https://images.unsplash.com/photo-1568901346375-23c9450c58cd?w=200', 'Burgers', 'Flame-grilled beef patty topped with juicy tomatoes, fresh lettuce, and creamy mayo.'),
                (?, 'Crispy Chicken Burger', 249.00, 4.2, 'https://images.unsplash.com/photo-1625813506062-0aeb1d7a094b?w=200', 'Burgers', 'Tender crispy chicken breast patty topped with shredded lettuce and mayo.'),
                (?, 'Golden Fries (Large)', 129.00, 4.0, 'https://images.unsplash.com/photo-1573080496219-bb080dd4f877?w=200', 'Sides', 'Hot, crispy, and perfectly salted golden potato fries.'),
                (?, 'Coca-Cola (Regular)', 89.00, 4.1, 'https://images.unsplash.com/photo-1622483767028-3f66f32aef97?w=200', 'Drinks', 'Refreshing Coca-Cola classic beverage served cold.')
            """, (bk_id, bk_id, bk_id, bk_id))
            
            cursor.execute("""
                INSERT INTO products (vendor_id, name, price, rating, image_url, category, description) VALUES
                (?, 'Caffe Latte', 345.00, 4.6, 'https://images.unsplash.com/photo-1541167760496-1628856ab772?w=200', 'Hot Coffee', 'Rich espresso combined with steamed milk and a light layer of foam.'),
                (?, 'Java Chip Frappuccino', 395.00, 4.8, 'https://images.unsplash.com/photo-1572490122747-3968b75cc699?w=200', 'Cold Coffee', 'Tall beverage of coffee blended with chocolate chips, milk, and ice, topped with whipped cream.'),
                (?, 'Chocolate Croissant', 220.00, 4.3, 'https://images.unsplash.com/photo-1555507036-ab1f4038808a?w=200', 'Bakery', 'Buttery, flaky croissant stuffed with rich dark chocolate fields.')
            """, (sb_id, sb_id, sb_id))
            
            cursor.execute("""
                INSERT INTO products (vendor_id, name, price, rating, image_url, category, description) VALUES
                (?, 'Galouti Kabab Platters', 699.00, 4.8, 'https://images.unsplash.com/photo-1603360946369-dc9bb6258143?w=200', 'Mains', 'Melt-in-your-mouth minced mutton kebabs served with mint chutney and rumali roti.'),
                (?, 'Tandoori Chicken Tikka', 549.00, 4.6, 'https://images.unsplash.com/photo-1599487488170-d11ec9c172f0?w=200', 'Appetizers', 'Spicy yogurt-marinated chicken chunks grilled in a traditional clay oven.')
            """, (gk_id, gk_id))
            
            conn.commit()
            
        conn.close()

    # User operations
    def get_user(self, email):
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE LOWER(email) = ?", (email.lower(),))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def create_user(self, email, name, password, mobile):
        conn = self.get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO users (email, name, password, mobile) VALUES (?, ?, ?, ?)",
                           (email.lower(), name, password, mobile))
            conn.commit()
        finally:
            conn.close()

    def update_profile(self, email, name, mobile):
        conn = self.get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET name = ?, mobile = ? WHERE LOWER(email) = ?",
                           (name, mobile, email.lower()))
            conn.commit()
        finally:
            conn.close()

    def update_password(self, email, password):
        conn = self.get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET password = ? WHERE LOWER(email) = ?",
                           (password, email.lower()))
            conn.commit()
        finally:
            conn.close()

    # Vendor operations
    def get_vendor(self, email):
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM vendors WHERE LOWER(email) = ?", (email.lower(),))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_vendor_by_id(self, vendor_id):
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_vendors(self, type_filter):
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM vendors WHERE type = ?", (type_filter,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def register_vendor(self, email, password, name, type_filter, terminal, gate, image_url):
        conn = self.get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO vendors (email, password, name, type, terminal, gate, rating, image_url, availability)
                VALUES (?, ?, ?, ?, ?, ?, 5.0, ?, 'Available')
            """, (email.lower(), password, name, type_filter, terminal, gate, image_url))
            conn.commit()
            last_id = cursor.lastrowid
            cursor.execute("SELECT * FROM vendors WHERE id = ?", (last_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def delete_vendor(self, email):
        conn = self.get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM vendors WHERE LOWER(email) = ?", (email.lower(),))
            conn.commit()
            return True
        except Exception as e:
            print(f"[SQLITE ERROR] delete_vendor failed: {e}")
            return False
        finally:
            conn.close()

    # Product operations
    def get_products(self, vendor_id=None):
        conn = self.get_conn()
        cursor = conn.cursor()
        if vendor_id:
            cursor.execute("SELECT * FROM products WHERE vendor_id = ?", (vendor_id,))
        else:
            cursor.execute("SELECT * FROM products")
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def add_product(self, vendor_id, name, price, category, description, image_url):
        conn = self.get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO products (vendor_id, name, price, rating, category, description, image_url)
                VALUES (?, ?, ?, 5.0, ?, ?, ?)
            """, (vendor_id, name, price, category, description, image_url))
            conn.commit()
            last_id = cursor.lastrowid
            cursor.execute("SELECT * FROM products WHERE id = ?", (last_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def update_product(self, product_id, name, price, category, description, image_url):
        conn = self.get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE products SET name = ?, price = ?, category = ?, description = ?, image_url = ?
                WHERE id = ?
            """, (name, price, category, description, image_url, product_id))
            conn.commit()
            cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def delete_product(self, product_id):
        conn = self.get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
            conn.commit()
        finally:
            conn.close()

    # Order operations
    def place_order(self, user_email, vendor_id, terminal, gate, total_price, items, payment_method='COD'):
        if total_price is None:
            try:
                total_price = sum(float(item.get('price', 0)) * int(item.get('quantity', 1)) for item in items)
            except Exception:
                total_price = 0.0

        conn = self.get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO orders (user_email, vendor_id, terminal, gate, status, total_price, payment_method)
                VALUES (?, ?, ?, ?, 'Pending', ?, ?)
            """, (user_email, vendor_id, terminal, gate, total_price, payment_method))
            order_id = cursor.lastrowid
            
            for item in items:
                p_id = item.get('product_id')
                qty = item.get('quantity', 1)
                price = item.get('price', 0.0)
                
                # Resilient product name resolution with lookups
                p_name = item.get('product_name') or item.get('name') or item.get('productName')
                if not p_name and p_id:
                    cursor.execute("SELECT name FROM products WHERE id = ?", (p_id,))
                    p_row = cursor.fetchone()
                    if p_row:
                        p_name = p_row['name']
                if not p_name:
                    p_name = "Unknown Item"

                cursor.execute("""
                    INSERT INTO order_items (order_id, product_id, quantity, price, product_name)
                    VALUES (?, ?, ?, ?, ?)
                """, (order_id, p_id, qty, price, p_name))
                
            conn.commit()
            cursor.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
            order_row = cursor.fetchone()
            return dict(order_row) if order_row else None
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            print(f"[SQLITE ERROR] place_order failed: {e}")
            raise e
        finally:
            conn.close()

    def get_orders(self, user_email):
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders WHERE user_email = ? ORDER BY id DESC", (user_email,))
        orders = [dict(row) for row in cursor.fetchall()]
        for order in orders:
            # get vendor name
            cursor.execute("SELECT name FROM vendors WHERE id = ?", (order['vendor_id'],))
            v_row = cursor.fetchone()
            order['vendor_name'] = v_row['name'] if v_row else "Unknown Restaurant"
            
            # get order items
            cursor.execute("SELECT * FROM order_items WHERE order_id = ?", (order['id'],))
            order['items'] = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return orders

    def get_order(self, order_id):
        conn = self.get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
            row = cursor.fetchone()
            if not row:
                return None
            order = dict(row)
            # get vendor name
            cursor.execute("SELECT name FROM vendors WHERE id = ?", (order['vendor_id'],))
            v_row = cursor.fetchone()
            order['vendor_name'] = v_row['name'] if v_row else "Unknown Restaurant"
            
            # get order items
            cursor.execute("SELECT * FROM order_items WHERE order_id = ?", (order['id'],))
            order['items'] = [dict(row) for row in cursor.fetchall()]
            return order
        finally:
            conn.close()

    def get_vendor_orders(self, vendor_id):
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders WHERE vendor_id = ? ORDER BY id DESC", (vendor_id,))
        orders = [dict(row) for row in cursor.fetchall()]
        for order in orders:
            cursor.execute("SELECT * FROM order_items WHERE order_id = ?", (order['id'],))
            order['items'] = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return orders

    def update_order_status(self, order_id, new_status):
        conn = self.get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE orders SET status = ? WHERE id = ?", (new_status, order_id))
            conn.commit()
            cursor.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_order_status(self, order_id):
        conn = self.get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM orders WHERE id = ?", (order_id,))
            row = cursor.fetchone()
            return row['status'] if row else None
        finally:
            conn.close()

    # Lounge bookings operations
    def book_lounge(self, user_email, vendor_id, booking_date, booking_time, slots):
        conn = self.get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO lounge_bookings (user_email, vendor_id, booking_date, booking_time, slots, status)
                VALUES (?, ?, ?, ?, ?, 'Pending')
            """, (user_email, vendor_id, booking_date, booking_time, slots))
            conn.commit()
            last_id = cursor.lastrowid
            cursor.execute("SELECT * FROM lounge_bookings WHERE id = ?", (last_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_bookings(self, user_email):
        conn = self.get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM lounge_bookings WHERE user_email = ? ORDER BY id DESC", (user_email,))
            bookings = [dict(row) for row in cursor.fetchall()]
            for booking in bookings:
                cursor.execute("SELECT name, terminal, gate, image_url FROM vendors WHERE id = ?", (booking['vendor_id'],))
                v_row = cursor.fetchone()
                if v_row:
                    booking['vendor_name'] = v_row['name']
                    booking['terminal'] = v_row['terminal']
                    booking['gate'] = v_row['gate']
                    booking['image_url'] = v_row['image_url']
                else:
                    booking['vendor_name'] = "Unknown Lounge"
                    booking['terminal'] = "-"
                    booking['gate'] = "-"
            return bookings
        finally:
            conn.close()

    def get_vendor_bookings(self, vendor_id):
        conn = self.get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM lounge_bookings WHERE vendor_id = ? ORDER BY id DESC", (vendor_id,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def update_booking_status(self, booking_id, new_status):
        conn = self.get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE lounge_bookings SET status = ? WHERE id = ?", (new_status, booking_id))
            conn.commit()
            cursor.execute("SELECT * FROM lounge_bookings WHERE id = ?", (booking_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def book_parking(self, user_email, zone, hours, plate_number, payment_method, total_price):
        conn = self.get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO parking_bookings (user_email, zone, hours, plate_number, payment_method, total_price, status)
                VALUES (?, ?, ?, ?, ?, ?, 'Pending')
            """, (user_email, zone, hours, plate_number, payment_method, total_price))
            conn.commit()
            last_id = cursor.lastrowid
            cursor.execute("SELECT * FROM parking_bookings WHERE id = ?", (last_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_parking_bookings(self, user_email):
        conn = self.get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM parking_bookings WHERE user_email = ? ORDER BY id DESC", (user_email,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    # Chat history operations
    def save_chat_message(self, email, user_type, session_id, message, is_user):
        conn = self.get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO chat_history (email, user_type, session_id, message, is_user)
                VALUES (?, ?, ?, ?, ?)
            """, (email, user_type, session_id, message, is_user))
            conn.commit()
        finally:
            conn.close()

db = LocalSQLiteDB()

# --- DATABASE INITIALIZATION ---
SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "https://ngpmzoxtmacqbsylifye.supabase.co")
SUPABASE_KEY: str = os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5ncG16b3h0bWFjcWJzeWxpZnllIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQ4MzM2OTEsImV4cCI6MjA5MDQwOTY5MX0.oKoaCRMC0wLmE08ZkCkP_fQuDtQGQV6EGxW9aQJ1bY4")

USE_SQLITE = False
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    # Check if Supabase DNS resolves & table queries succeed
    supabase.table('users').select('name').limit(1).execute()
    print("[DATABASE STATUS] Connected to Supabase Cloud Storage.")
except Exception as e:
    print(f"[DATABASE STATUS] Supabase cloud is unreachable ({e}). Seamlessly activated Local SQLite Persistent Fallback.")
    USE_SQLITE = True

@app.route('/', methods=['GET'])
def home():
    return jsonify({"status": "online", "server": "AeroAssist AI Backend API is Alive and Running!"})

# In-memory storage for temporary OTPs before they are officially verified
otp_store = {}

def send_smtp_email(to_email, otp, name="Valued User", custom_message=None):
    # Dynamic headers and description
    if custom_message:
        pre_title = "SECURITY VERIFICATION"
        desc_text = custom_message
    else:
        pre_title = "ACCOUNT REGISTRATION VERIFICATION"
        desc_text = "Use the following secure code to complete your <strong>Account Registration</strong> request on our platform."

    html_content = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap');
    body {{ font-family: 'Inter', 'Segoe UI', sans-serif; margin: 0; padding: 30px 20px;
           background: linear-gradient(135deg, #0a0f1e 0%, #0d1b3e 40%, #0a2a5e 70%, #0e3a6e 100%); min-height: 100vh; }}
    .container {{ max-width: 580px; margin: 0 auto;
                  background: linear-gradient(160deg, rgba(13,30,64,0.97) 0%, rgba(8,18,45,0.99) 100%);
                  border-radius: 20px; overflow: hidden;
                  box-shadow: 0 20px 60px rgba(0,0,0,0.6), 0 0 0 1px rgba(255,255,255,0.07); }}
    .header {{ background: linear-gradient(135deg, #0b2d6b 0%, #0d3b8f 50%, #0a52c4 100%);
               padding: 40px 20px; text-align: center; position: relative; overflow: hidden; }}
    .header::before {{ content: '✈'; position: absolute; font-size: 120px; opacity: 0.1;
                        top: -20px; right: -10px; transform: rotate(-30deg); }}
    .header h1 {{ color: #ffffff; margin: 0; font-size: 28px; font-weight: 800; letter-spacing: 2px; }}
    .header p {{ color: #7fb3ff; margin: 8px 0 0 0; font-size: 11px; font-weight: 600; letter-spacing: 3px; text-transform: uppercase; }}
    .content {{ padding: 40px 30px; }}
    .pre-title {{ color: #4a9eff; font-size: 11px; font-weight: 700; letter-spacing: 2px; text-transform: uppercase; margin-bottom: 10px; }}
    .title {{ color: #ffffff; font-size: 30px; font-weight: 800; margin: 0 0 20px 0; line-height: 1.2; }}
    .greeting {{ color: #c8d8ff; font-size: 17px; margin-bottom: 15px; }}
    .greeting strong {{ color: #ffffff; font-weight: 700; }}
    .desc {{ color: #8fa8cc; font-size: 15px; line-height: 1.6; margin-bottom: 30px; }}
    .desc strong {{ color: #c8d8ff; }}
    .otp-card {{ background: linear-gradient(135deg, #0d2d5e 0%, #0a1f45 100%);
                  border: 1px solid rgba(74,158,255,0.3); border-radius: 16px;
                  padding: 30px; text-align: center; margin-bottom: 30px;
                  box-shadow: 0 0 30px rgba(10,82,196,0.3); }}
    .otp-subtitle {{ color: #4a9eff; font-size: 11px; font-weight: 700; letter-spacing: 3px; text-transform: uppercase; margin-bottom: 20px; }}
    .otp-code {{ color: #ffffff; font-size: 52px; font-weight: 800; letter-spacing: 18px; margin: 0 0 20px 18px;
                  font-family: 'Courier New', monospace; text-shadow: 0 0 20px rgba(74,158,255,0.5); }}
    .otp-divider {{ height: 1px; background: linear-gradient(90deg, transparent, rgba(74,158,255,0.4), transparent); margin-bottom: 15px; }}
    .otp-timer {{ color: #ff6b6b; font-size: 13px; font-weight: 600; }}
    .notice {{ background: rgba(255,100,100,0.08); border: 1px solid rgba(255,100,100,0.2);
               border-radius: 10px; padding: 15px; font-size: 13px; color: #ff9a9a; line-height: 1.5; }}
    .notice strong {{ font-weight: 700; color: #ffb3b3; }}
    td {{ color: #8fa8cc !important; }}
</style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>AeroAssist AI</h1>
            <p>INTELLIGENT AIRPORT & FLIGHT NAVIGATION PLATFORM</p>
        </div>
        <div class="content">
            <div class="pre-title">{pre_title}</div>
            <h2 class="title">Your One-Time<br>Password</h2>
            
            <div class="greeting">Hello, <strong>{name}</strong> 👋</div>
            <div class="desc">{desc_text}</div>
            
            <div class="otp-card">
                <div class="otp-subtitle">SECURE VERIFICATION CODE</div>
                <div class="otp-code">{otp}</div>
                <div class="otp-divider"></div>
                <div class="otp-timer">⏱️ Valid for 5 minutes only</div>
            </div>
            
            <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom: 30px;">
                <tr>
                    <td width="31%" align="center" style="border: 1px solid #e2e8f0; border-radius: 8px; padding: 15px 5px; font-size: 12px; font-weight: 700; color: #7f99b2;">
                        <span style="font-size: 18px;">🔒</span><br>Secure
                    </td>
                    <td width="3%"></td>
                    <td width="32%" align="center" style="background-color: #fffdf5; border: 1px solid #fceea7; border-radius: 8px; padding: 15px 5px; font-size: 12px; font-weight: 700; color: #b58d00;">
                        <span style="font-size: 18px;">⚡</span><br>Single Use
                    </td>
                    <td width="3%"></td>
                    <td width="31%" align="center" style="background-color: #f0fbff; border: 1px solid #bce6f5; border-radius: 8px; padding: 15px 5px; font-size: 12px; font-weight: 700; color: #0087b5;">
                        <span style="font-size: 18px;">✈️</span><br>Aero Assist
                    </td>
                </tr>
            </table>
            
            <div class="notice">
                <strong>Security Notice:</strong> If you did not request this code, please ignore this email. Your account remains protected.
            </div>
        </div>
    </div>
</body>
</html>
"""

    # 1. Resend HTTP API Dispatcher (Render Free Tier Firewall Bypass)
    resend_key = os.environ.get("RESEND_API_KEY")
    if resend_key:
        resend_key = resend_key.strip()
        print("[SMTP REDIRECT] Resend API Key detected! Delivering email via HTTPS API to bypass Render firewall blocks...")
        import requests
        try:
            url = "https://api.resend.com/emails"
            headers = {
                "Authorization": f"Bearer {resend_key}",
                "Content-Type": "application/json"
            }
            resend_sender = os.environ.get("RESEND_SENDER_EMAIL", "onboarding@resend.dev").strip()
            data = {
                "from": f"AeroAssist Security <{resend_sender}>",
                "to": to_email,
                "subject": f"🔒 {otp} is your AeroAssist Verification Code",
                "html": html_content
            }
            response = requests.post(url, json=data, headers=headers, timeout=12)
            if response.status_code in [200, 201]:
                print(f"[RESEND SUCCESS] Email successfully delivered to {to_email}!")
                return True
            else:
                print(f"[RESEND ERROR] HTTP Status {response.status_code}: {response.text}. Attempting SMTP fallback...")
        except Exception as e_resend:
            print(f"[RESEND EXCEPTION] HTTPS dispatch failed: {e_resend}. Attempting SMTP fallback...")

    # 2. Classic SMTP Dispatcher (Local Development)
    sender_email = os.environ.get("SMTP_SENDER_EMAIL", "noreplyaeroassistapp@gmail.com").strip()
    sender_password = os.environ.get("SMTP_SENDER_PASSWORD", "bxig ymbt ifsu lalk").strip()
    to_email = to_email.strip()

    try:
        msg = MIMEMultipart("alternative")
        msg['From'] = f"AeroAssist Security <{sender_email}>"
        msg['To'] = to_email
        msg['Subject'] = f"🔒 {otp} is your AeroAssist Verification Code"
        msg.attach(MIMEText(html_content, 'html', 'utf-8'))
        text = msg.as_string()

        try:
            print("[SMTP] Attempting delivery via TLS on Port 587...")
            server = smtplib.SMTP('smtp.gmail.com', 587, timeout=10)
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, to_email, text)
            server.quit()
            print("[SMTP] Success! OTP delivered via TLS Port 587.")
            return True
        except Exception as e_tls:
            print(f"[SMTP WARNING] TLS Port 587 failed: {e_tls}. Retrying via SSL on Port 465...")
            try:
                server = smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=10)
                server.login(sender_email, sender_password)
                server.sendmail(sender_email, to_email, text)
                server.quit()
                print("[SMTP] Success! OTP delivered via SSL Port 465.")
                return True
            except Exception as e_ssl:
                print(f"[SMTP ERROR] SSL Port 465 also failed: {e_ssl}. Email delivery unsuccessful.")
                return False
    except Exception as e_outer:
        print("[SMTP FATAL ERROR] Failed to construct or send email:", str(e_outer))
        return False

@app.route('/api/google-login', methods=['POST'])
def google_login():
    """Handles Google Sign-In: direct login for existing users, OTP for new ones."""
    data = request.json
    email = (data.get('email') or '').strip().lower()
    name = data.get('name', 'Google User')

    existing_user = None
    if USE_SQLITE:
        existing_user = db.get_user(email)
    else:
        try:
            response = supabase.table('users').select('name, mobile').eq('email', email).execute()
            existing_user = response.data[0] if response.data else None
        except Exception as e:
            print("[FALLBACK] Supabase error in google_login:", str(e))
            existing_user = db.get_user(email)

    if existing_user:
        # Existing user — log in directly, no OTP needed
        return jsonify({
            "status": "success",
            "existing": True,
            "name": existing_user.get('name'),
            "mobile": existing_user.get('mobile', ""),
            "message": "Welcome back! Logged in directly."
        })
    else:
        # New user — generate and send OTP
        otp = str(random.randint(1000, 9999))
        otp_store[email] = {
            "otp": otp,
            "name": name,
            "password": f"google_oauth_{email}",
            "mobile": ""
        }
        email_sent = send_smtp_email(email, otp, name=name)
        print(f"\n[GOOGLE LOGIN LOG] -> New user OTP '{otp}' sent to: {email}")
        if email_sent:
            return jsonify({"status": "success", "existing": False, "message": "OTP sent to your Google email."})
        else:
            print(f"\n[SERVER PRIVATE LOG - DEVELOPMENT ONLY] -> SMTP dispatch failed. Fallback OTP for new Google user {email} is: {otp}")
            return jsonify({"status": "error", "message": "Failed to send OTP verification email. Please verify your SMTP settings."}), 500

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    email = (data.get('email') or '').strip().lower()
    
    existing_user = None
    if USE_SQLITE:
        existing_user = db.get_user(email)
    else:
        try:
            response = supabase.table('users').select('email').eq('email', email).execute()
            existing_user = response.data[0] if response.data else None
        except Exception as e:
            print("[FALLBACK] Supabase error in register check:", str(e))
            existing_user = db.get_user(email)

    if existing_user:
         return jsonify({"status": "error", "message": "Email already registered"}), 400

    # Generate 4-digit code
    otp = str(random.randint(1000, 9999))
    
    # Store registration temporarily pending verification
    otp_store[email] = {
        "otp": otp,
        "name": data.get('name'),
        "password": data.get('password'),
        "mobile": data.get('mobile')
    }
    
    # Send the real SMTP HTML email payload specifically formatted to precisely mirror the User's reference
    email_sent = send_smtp_email(email, otp, name=data.get('name', 'Valued User'))

    print(f"\n[SERVER SECURE LOG] -> Sent OTP '{otp}' to target: {email}")
    
    if email_sent:
        return jsonify({"status": "success", "message": "OTP blasted to user email inbox."})
    else:
        print(f"\n[SERVER PRIVATE LOG - DEVELOPMENT ONLY] -> SMTP dispatch failed. Fallback OTP for register user {email} is: {otp}")
        return jsonify({"status": "error", "message": "Failed to dispatch verification email. Please check server settings."}), 500

@app.route('/api/verify', methods=['POST'])
def verify():
    data = request.json
    email = data.get('email')
    otp = data.get('otp')
    
    if email in otp_store and otp_store[email]['otp'] == str(otp):
        # Validate and formally migrate to SQLite persistent storage
        user_data = otp_store[email]
        
        if USE_SQLITE:
            db.create_user(email, user_data['name'], user_data['password'], user_data['mobile'])
        else:
            try:
                supabase.table('users').upsert({
                    'email': email,
                    'name': user_data['name'],
                    'password': user_data['password'],
                    'mobile': user_data['mobile']
                }).execute()
            except Exception as e:
                print("[FALLBACK] Supabase error in verify upsert:", str(e))
                db.create_user(email, user_data['name'], user_data['password'], user_data['mobile'])
        
        del otp_store[email]
        return jsonify({"status": "success", "message": "User Authenticated and Verified.", "name": user_data['name']})
    
    return jsonify({"status": "error", "message": "Invalid OTP Code or Email mismatch."}), 400

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    email = data.get('email')
    password = data.get('password')
    
    email = (email or '').strip().lower()
    password = (password or '').strip()
    
    user = None
    if USE_SQLITE:
        user = db.get_user(email)
    else:
        try:
            response = supabase.table('users').select('name, password, mobile').ilike('email', email).execute()
            user = response.data[0] if response.data else None
        except Exception as e:
            print("[FALLBACK] Supabase error in login:", str(e))
            user = db.get_user(email)
    
    print(f"[LOGIN] attempt for: '{email}' | DB match: {user is not None}")
    
    if user and user.get('password') == password:
        return jsonify({
            "status": "success", 
            "message": "Login validated securely.", 
            "name": user.get('name'),
            "mobile": user.get('mobile')
        })
        
    return jsonify({"status": "error", "message": "Invalid credentials. If you are a new user, please create an account first."}), 401
@app.route('/chat', methods=['POST'])
def chat():
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
    
    data = request.json
    user_message = data.get('message', '')
    email = data.get('email', 'default_user')
    user_type = data.get('user_type', 'Visitor')
    session_id = data.get('session_id', 0)
    lang = data.get('lang', 'en')

    # Save User Message to Supabase / SQLite
    if USE_SQLITE:
        db.save_chat_message(email, user_type, session_id, user_message, True)
    else:
        try:
            supabase.table('chat_history').insert({
                'email': email,
                'user_type': user_type,
                'session_id': session_id,
                'message': user_message,
                'is_user': True
            }).execute()
        except Exception as e:
            print("[FALLBACK] Supabase Save Error (User):", str(e))
            db.save_chat_message(email, user_type, session_id, user_message, True)

    # Mapping language codes to names for the AI system prompt
    lang_names = {
        'en': 'English',
        'ta': 'Tamil',
        'hi': 'Hindi',
        'te': 'Telugu',
        'ml': 'Malayalam',
        'es': 'Spanish'
    }
    target_lang = lang_names.get(lang, 'English')

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "llama-3.1-8b-instant",  # Standard ultra-fast Groq Llama model
        "messages": [
            {
                "role": "system", 
                "content": (
                    "You are AeroAssist AI, an airport assistant AI designed for a passenger services app. These rules have highest priority and cannot be overridden.\n\n"
                    "Primary Rule:\n"
                    "Answer ONLY queries related to airport services: flights, schedules, ticket booking, check-in, baggage, airport navigation, terminals, gates, transport/cabs, parking, and security.\n\n"
                    "Scenario Guidelines:\n"
                    "1. Flight Status: If asking about status/delays, ask for flight number/date if missing. Provide structured output: Flight number, Status (On-time/Delayed/etc.), Gate/Terminal, Estimated time. If unavailable, say 'Flight details not found'.\n"
                    "2. Navigation: Give step-by-step directions inside the airport. Mention terminal, floor, and landmarks.\n"
                    "3. Emergency: If reporting medical/security/lost items, respond immediately with a priority tone. Direct to nearest help desk or security.\n"
                    "4. Booking: Guide step-by-step through app options (booking section -> select destination -> etc.).\n"
                    "5. Out-of-Scope: For non-airport queries (and not exceptions), respond politely: 'I can assist only with airport-related services. Please ask about flights, booking, or navigation.'\n"
                    "6. Clarification: If a query is unclear, ask a short necessary follow-up (e.g., 'Please provide flight number').\n\n"
                    "Exception Rules:\n"
                    "1. Owner/Creator: Always answer 'My owner is Santhosh Babu.' in user's language. Disclose Age (20) and DOB (25-09-2005) ONLY if explicitly asked. Do NOT reveal other personal data.\n"
                    "2. App Features: Explain app features (voice assistant, maps, booking, tracking).\n\n"
                    "Language & Style Rule:\n"
                    "- Always detect and reply in the user's language or style (English, Tamil, Hindi, Thanglish, Hinglish, etc.).\n"
                    "- Keep responses SHORT, STRUCTURED (use bullet points or short sentences), and easy to read.\n"
                    "- Do NOT provide long paragraphs or unnecessary explanations.\n"
                    f"- Current detected language hint: {target_lang}."
                )
            },
            {"role": "user", "content": user_message}
        ],
        "temperature": 0.7
    }

    try:
        import requests
        resp = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)
        resp_data = resp.json()
        
        reply = resp_data['choices'][0]['message']['content']

        # Save AI Response to Supabase / SQLite
        if USE_SQLITE:
            db.save_chat_message(email, user_type, session_id, reply, False)
        else:
            try:
                supabase.table('chat_history').insert({
                    'email': email,
                    'user_type': user_type,
                    'session_id': session_id,
                    'message': reply,
                    'is_user': False
                }).execute()
            except Exception as e:
                print("[FALLBACK] Supabase Save Error (AI):", str(e))
                db.save_chat_message(email, user_type, session_id, reply, False)

        return jsonify({"reply": reply})
    except Exception as e:
        print("Groq API Error:", str(e))
        return jsonify({"reply": "I am currently offline or missing my API configuration."}), 500

@app.route('/api/save-chat', methods=['POST'])
def save_chat():
    data = request.json
    email = data.get('email')
    user_type = data.get('user_type')
    session_id = data.get('session_id')
    message = data.get('message')
    is_user = data.get('is_user', True)

    if USE_SQLITE:
        db.save_chat_message(email, user_type, session_id, message, is_user)
        return jsonify({"status": "success"})
    else:
        try:
            supabase.table('chat_history').insert({
                'email': email,
                'user_type': user_type,
                'session_id': session_id,
                'message': message,
                'is_user': is_user
            }).execute()
            return jsonify({"status": "success"})
        except Exception as e:
            print("[FALLBACK] Supabase Save Error:", str(e))
            db.save_chat_message(email, user_type, session_id, message, is_user)
            return jsonify({"status": "success", "fallback": True})

@app.route('/api/update-profile', methods=['POST'])
def update_profile():
    data = request.json
    email = data.get('email')
    name = data.get('name')
    mobile = data.get('mobile')
    
    if USE_SQLITE:
        db.update_profile(email, name, mobile)
    else:
        try:
            supabase.table('users').update({
                'name': name,
                'mobile': mobile
            }).ilike('email', email.lower()).execute()
        except Exception as e:
            print("[FALLBACK] Supabase update-profile error:", str(e))
            db.update_profile(email, name, mobile)
            
    return jsonify({"status": "success", "message": "Profile updated successfully"})

@app.route('/api/password-reset-request', methods=['POST'])
def password_reset_request():
    data = request.json
    email = data.get('email')
    
    user = None
    if USE_SQLITE:
        user = db.get_user(email)
    else:
        try:
            response = supabase.table('users').select('name').ilike('email', email.lower()).execute()
            user = response.data[0] if response.data else None
        except Exception as e:
            print("[FALLBACK] Supabase password reset request error:", str(e))
            user = db.get_user(email)
            
    if not user:
        return jsonify({"status": "error", "message": "Email not recognized"}), 404
        
    otp = str(random.randint(1000, 9999))
    otp_store[email.lower() + "_reset"] = {"otp": otp, "name": user.get('name')}
    
    # Custom message as per User Request
    message = "This is your OTP to change password. Please verify this code to securely update your account credentials."
    email_sent = send_smtp_email(email, otp, name=user.get('name'), custom_message=message)
    if email_sent:
        return jsonify({"status": "success", "message": "Verification code sent to email"})
    else:
        print(f"\n[SERVER PRIVATE LOG - DEVELOPMENT ONLY] -> SMTP dispatch failed. Fallback OTP for password reset user {email} is: {otp}")
        return jsonify({"status": "error", "message": "Failed to send verification code. Please check server settings."}), 500

@app.route('/api/password-reset-confirm', methods=['POST'])
def password_reset_confirm():
    data = request.json
    email = data.get('email')
    otp = data.get('otp')
    new_password = data.get('new_password')
    
    key = email.lower() + "_reset"
    if key in otp_store and otp_store[key]['otp'] == str(otp):
        if USE_SQLITE:
            db.update_password(email, new_password)
        else:
            try:
                supabase.table('users').update({
                    'password': new_password
                }).ilike('email', email.lower()).execute()
            except Exception as e:
                print("[FALLBACK] Supabase password reset confirm error:", str(e))
                db.update_password(email, new_password)
                
        del otp_store[key]
        return jsonify({"status": "success", "message": "Password changed successfully"})
    return jsonify({"status": "error", "message": "Invalid OTP Code"}), 400
        


# --- NEW VENDOR & ORDER / LOUNGE BOOKING SYSTEM ENDPOINTS ---

@app.route('/api/vendors/register', methods=['POST'])
def vendor_register():
    data = request.json
    admin_key = data.get('admin_key')
    
    # Enforce Admin-only restriction
    if admin_key != "admin_aeroassist_2026":
        return jsonify({"status": "error", "message": "Unauthorized: Only the admin can register vendor accounts"}), 403

    email = data.get('email')
    password = data.get('password')
    name = data.get('name')
    v_type = data.get('type')  # 'restaurant' or 'lounge'
    terminal = data.get('terminal', 'Terminal 1')
    gate = data.get('gate', 'Gate 1')
    image_url = data.get('image_url', '')

    if USE_SQLITE:
        existing = db.get_vendor(email)
        if existing:
            return jsonify({"status": "error", "message": "Vendor email already registered"}), 400
        vendor = db.register_vendor(email, password, name, v_type, terminal, gate, image_url)
        return jsonify({"status": "success", "message": "Vendor registered successfully", "vendor": vendor})
    else:
        try:
            response = supabase.table('vendors').select('email').eq('email', email).execute()
            if response.data:
                return jsonify({"status": "error", "message": "Vendor email already registered"}), 400

            ins_resp = supabase.table('vendors').insert({
                'email': email,
                'password': password,
                'name': name,
                'type': v_type,
                'terminal': terminal,
                'gate': gate,
                'rating': 5.0,
                'image_url': image_url,
                'availability': 'Available'
            }).execute()
            return jsonify({"status": "success", "message": "Vendor registered successfully", "vendor": ins_resp.data[0]})
        except Exception as e:
            print("[FALLBACK] Supabase register error:", str(e))
            existing = db.get_vendor(email)
            if existing:
                return jsonify({"status": "error", "message": "Vendor email already registered"}), 400
            vendor = db.register_vendor(email, password, name, v_type, terminal, gate, image_url)
            return jsonify({"status": "success", "message": "Vendor registered successfully", "vendor": vendor})

@app.route('/api/vendors/delete', methods=['POST'])
def delete_vendor():
    data = request.json
    admin_key = data.get('admin_key')
    email = data.get('email')

    # Enforce Admin-only restriction
    if admin_key != "admin_aeroassist_2026":
        return jsonify({"status": "error", "message": "Unauthorized: Only the admin can remove vendor accounts"}), 403

    if not email:
        return jsonify({"status": "error", "message": "Missing email parameter"}), 400

    if USE_SQLITE:
        success = db.delete_vendor(email)
        if success:
            return jsonify({"status": "success", "message": "Vendor account removed successfully"})
        return jsonify({"status": "error", "message": "Failed to remove vendor"}), 500
    try:
        supabase.table('vendors').delete().eq('email', email).execute()
        # Clean up database fallback as well
        db.delete_vendor(email)
        return jsonify({"status": "success", "message": "Vendor account removed successfully"})
    except Exception as e:
        print("[FALLBACK] Supabase delete vendor error:", str(e))
        success = db.delete_vendor(email)
        if success:
            return jsonify({"status": "success", "message": "Vendor account removed successfully"})
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/vendors/login', methods=['POST'])
def vendor_login():
    data = request.json
    email = (data.get('email') or '').strip().lower()
    password = (data.get('password') or '').strip()

    vendor = None
    if USE_SQLITE:
        vendor = db.get_vendor(email)
    else:
        try:
            response = supabase.table('vendors').select('*').eq('email', email).execute()
            vendor = response.data[0] if response.data else None
        except Exception as e:
            print("[FALLBACK] Supabase vendor login error:", str(e))
            vendor = db.get_vendor(email)

    if not vendor:
        return jsonify({"status": "error", "message": "Vendor email not found"}), 404
    
    if vendor.get('password') == password:
        return jsonify({
            "status": "success",
            "message": "Vendor login successful",
            "vendor": {
                "id": vendor.get('id'),
                "email": vendor.get('email'),
                "name": vendor.get('name'),
                "type": vendor.get('type'),
                "terminal": vendor.get('terminal'),
                "gate": vendor.get('gate'),
                "rating": float(vendor.get('rating') or 5.0),
                "availability": vendor.get('availability', 'Available')
            }
        })
    return jsonify({"status": "error", "message": "Incorrect password"}), 401

@app.route('/api/restaurants', methods=['GET'])
def get_restaurants():
    if USE_SQLITE:
        return jsonify({"status": "success", "restaurants": db.get_vendors('restaurant')})
    try:
        response = supabase.table('vendors').select('*').eq('type', 'restaurant').execute()
        return jsonify({"status": "success", "restaurants": response.data})
    except Exception as e:
        print("[FALLBACK] Supabase restaurants fetch error:", str(e))
        return jsonify({"status": "success", "restaurants": db.get_vendors('restaurant')})

@app.route('/api/shopping', methods=['GET'])
def get_shopping():
    # Dynamic self-seeding of Shopping Vendors and Products if empty
    conn = db.get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM vendors WHERE type = 'shopping'")
    count = cursor.fetchone()[0]
    if count == 0:
        cursor.execute("""
            INSERT INTO vendors (email, password, name, type, terminal, gate, rating, image_url, availability) VALUES
            ('dutyfree@airport.com', 'vendor123', 'Duty Free Americas', 'shopping', 'Terminal 1', 'Gate 18', 4.5, 'https://images.unsplash.com/photo-1544816155-12df9643f363?w=500', 'Available'),
            ('relay@airport.com', 'vendor123', 'Relay Books & Travel', 'shopping', 'Terminal 1', 'Gate 12', 4.2, 'https://images.unsplash.com/photo-1507842217343-583bb7270b66?w=500', 'Available'),
            ('tech2go@airport.com', 'vendor123', 'Tech2Go', 'shopping', 'Terminal 2', 'Gate 28', 4.6, 'https://images.unsplash.com/photo-1531297484001-80022131f5a1?w=500', 'Available')
        """)
        conn.commit()
        
        cursor.execute("SELECT id FROM vendors WHERE email = 'dutyfree@airport.com'")
        df_id = cursor.fetchone()[0]
        cursor.execute("SELECT id FROM vendors WHERE email = 'relay@airport.com'")
        rl_id = cursor.fetchone()[0]
        cursor.execute("SELECT id FROM vendors WHERE email = 'tech2go@airport.com'")
        tg_id = cursor.fetchone()[0]
        
        cursor.execute("""
            INSERT INTO products (vendor_id, name, price, rating, image_url, category, description) VALUES
            (?, 'Chanel No. 5 Perfume', 8500.00, 4.5, 'https://images.unsplash.com/photo-1544816155-12df9643f363?w=200', 'Fragrances', 'The ultimate luxury fragrance for women, a timeless classic.'),
            (?, 'Macallan 12 Year Single Malt', 7200.00, 4.7, 'https://images.unsplash.com/photo-1527061011665-3652c757a4d4?w=200', 'Liquor', 'Premium single malt scotch whisky matured in sherry seasoned oak casks.'),
            (?, 'Swiss Lindt Dark Truffles', 1200.00, 4.3, 'https://images.unsplash.com/photo-1548907040-4d42b52115ca?w=200', 'Chocolates', 'Decadent dark chocolate truffles with a smooth melting center.')
        """, (df_id, df_id, df_id))
        
        cursor.execute("""
            INSERT INTO products (vendor_id, name, price, rating, image_url, category, description) VALUES
            (?, 'Atomic Habits (James Clear)', 399.00, 4.8, 'https://images.unsplash.com/photo-1544716278-ca5e3f4abd8c?w=200', 'Books', 'An easy & proven way to build good habits & break bad ones.'),
            (?, 'Travel Neck Pillow (Memory Foam)', 999.00, 4.2, 'https://images.unsplash.com/photo-1520038410233-7141be7e6f97?w=200', 'Travel Gear', 'Ergonomic memory foam neck support pillow for comfortable long flights.'),
            (?, 'AeroAssist Notebook', 299.00, 4.5, 'https://images.unsplash.com/photo-1531346878377-a5be20888e57?w=200', 'Stationery', 'Sleek, faux-leather travel notebook with high-quality cream pages.')
        """, (rl_id, rl_id, rl_id))
        
        cursor.execute("""
            INSERT INTO products (vendor_id, name, price, rating, image_url, category, description) VALUES
            (?, 'Sony WH-1000XM4 Headphones', 19990.00, 4.9, 'https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=200', 'Audio', 'Industry-leading noise cancelling overhead headphones with premium sound.'),
            (?, 'Anker PowerCore 20000mAh', 2499.00, 4.6, 'https://images.unsplash.com/photo-1609592424087-434a6efc687e?w=200', 'Accessories', 'Ultra-high capacity power bank with fast-charging technology.'),
            (?, 'Universal Travel Adapter', 899.00, 4.4, 'https://images.unsplash.com/photo-1583863788434-e58a36330cf0?w=200', 'Accessories', 'All-in-one international plug adapter covering over 150 countries.')
        """, (tg_id, tg_id, tg_id))
        
        conn.commit()
    conn.close()

    if USE_SQLITE:
        return jsonify({"status": "success", "shopping": db.get_vendors('shopping')})
    try:
        response = supabase.table('vendors').select('*').eq('type', 'shopping').execute()
        return jsonify({"status": "success", "shopping": response.data})
    except Exception as e:
        print("[FALLBACK] Supabase shopping fetch error:", str(e))
        return jsonify({"status": "success", "shopping": db.get_vendors('shopping')})

@app.route('/api/lounges', methods=['GET'])
def get_lounges():
    if USE_SQLITE:
        return jsonify({"status": "success", "lounges": db.get_vendors('lounge')})
    try:
        response = supabase.table('vendors').select('*').eq('type', 'lounge').execute()
        return jsonify({"status": "success", "lounges": response.data})
    except Exception as e:
        print("[FALLBACK] Supabase lounges fetch error:", str(e))
        return jsonify({"status": "success", "lounges": db.get_vendors('lounge')})

@app.route('/api/products', methods=['GET'])
def get_products():
    vendor_id = request.args.get('vendor_id')
    if USE_SQLITE:
        return jsonify({"status": "success", "products": db.get_products(vendor_id)})
    try:
        query = supabase.table('products').select('*')
        if vendor_id:
            query = query.eq('vendor_id', vendor_id)
        response = query.execute()
        return jsonify({"status": "success", "products": response.data})
    except Exception as e:
        print("[FALLBACK] Supabase products fetch error:", str(e))
        return jsonify({"status": "success", "products": db.get_products(vendor_id)})

@app.route('/api/orders', methods=['POST'])
def place_order():
    data = request.json
    user_email = data.get('user_email')
    vendor_id = data.get('vendor_id')
    terminal = data.get('terminal')
    gate = data.get('gate')
    total_price = data.get('total_price')
    payment_method = data.get('payment_method', 'COD')
    items = data.get('items', [])

    if USE_SQLITE:
        order = db.place_order(user_email, vendor_id, terminal, gate, total_price, items, payment_method)
        if order:
            return jsonify({"status": "success", "message": "Order placed successfully", "order_id": order['id'], "order": order})
        return jsonify({"status": "error", "message": "Failed to create order"}), 500
    try:
        order_resp = supabase.table('orders').insert({
            'user_email': user_email,
            'vendor_id': vendor_id,
            'terminal': terminal,
            'gate': gate,
            'status': 'Pending',
            'total_price': total_price,
            'payment_method': payment_method
        }).execute()
        
        if not order_resp.data:
            return jsonify({"status": "error", "message": "Failed to create order"}), 500
            
        order_id = order_resp.data[0]['id']
        
        order_items_data = []
        for item in items:
            p_id = item.get('product_id')
            qty = item.get('quantity', 1)
            price = item.get('price', 0.0)
            
            p_name = item.get('product_name') or item.get('name') or item.get('productName')
            if not p_name:
                p_name = "Unknown Item"
                
            order_items_data.append({
                'order_id': order_id,
                'product_id': p_id,
                'quantity': qty,
                'price': price,
                'product_name': p_name
            })
            
        if order_items_data:
            supabase.table('order_items').insert(order_items_data).execute()
            
        return jsonify({
            "status": "success", 
            "message": "Order placed successfully", 
            "order_id": order_id,
            "order": order_resp.data[0]
        })
    except Exception as e:
        print("[FALLBACK] Supabase place order error:", str(e))
        order = db.place_order(user_email, vendor_id, terminal, gate, total_price, items, payment_method)
        if order:
            return jsonify({"status": "success", "message": "Order placed successfully", "order_id": order['id'], "order": order})
        return jsonify({"status": "error", "message": str(e)}), 500
@app.route('/api/orders/history', methods=['GET'])
@app.route('/api/orders', methods=['GET'])
def order_history():
    user_email = request.args.get('user_email') or request.args.get('email')
    if not user_email:
        return jsonify({"status": "error", "message": "Missing user_email parameter"}), 400
    if USE_SQLITE:
        return jsonify({"status": "success", "orders": db.get_orders(user_email)})
    try:
        orders_resp = supabase.table('orders').select('*').eq('user_email', user_email).order('id', desc=True).execute()
        orders = orders_resp.data or []
        for order in orders:
            v_resp = supabase.table('vendors').select('name').eq('id', order['vendor_id']).execute()
            order['vendor_name'] = v_resp.data[0]['name'] if v_resp.data else "Unknown Restaurant"
            items_resp = supabase.table('order_items').select('*').eq('order_id', order['id']).execute()
            order['items'] = items_resp.data or []
        return jsonify({"status": "success", "orders": orders})
    except Exception as e:
        print("[FALLBACK] Supabase order history fetch error:", str(e))
        return jsonify({"status": "success", "orders": db.get_orders(user_email)})

@app.route('/api/orders/<int:order_id>', methods=['GET'])
def get_order_details(order_id):
    if USE_SQLITE:
        order = db.get_order(order_id)
        if order:
            return jsonify({"status": "success", "order": order})
        return jsonify({"status": "error", "message": "Order not found"}), 404
    try:
        order_resp = supabase.table('orders').select('*').eq('id', order_id).execute()
        if not order_resp.data:
            return jsonify({"status": "error", "message": "Order not found"}), 404
        order = order_resp.data[0]
        v_resp = supabase.table('vendors').select('name').eq('id', order['vendor_id']).execute()
        order['vendor_name'] = v_resp.data[0]['name'] if v_resp.data else "Unknown Restaurant"
        items_resp = supabase.table('order_items').select('*').eq('order_id', order['id']).execute()
        order['items'] = items_resp.data or []
        return jsonify({"status": "success", "order": order})
    except Exception as e:
        print("[FALLBACK] Supabase get order details error:", str(e))
        order = db.get_order(order_id)
        if order:
            return jsonify({"status": "success", "order": order})
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/orders/<int:order_id>/status', methods=['GET'])
def get_order_status(order_id):
    if USE_SQLITE:
        status = db.get_order_status(order_id)
        if status:
            return jsonify({"status": "success", "order_id": order_id, "order_status": status})
        return jsonify({"status": "error", "message": "Order not found"}), 404
    try:
        response = supabase.table('orders').select('status').eq('id', order_id).execute()
        if response.data:
            return jsonify({"status": "success", "order_id": order_id, "order_status": response.data[0]['status']})
        return jsonify({"status": "error", "message": "Order not found"}), 404
    except Exception as e:
        print("[FALLBACK] Supabase get order status error:", str(e))
        status = db.get_order_status(order_id)
        if status:
            return jsonify({"status": "success", "order_id": order_id, "order_status": status})
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/lounge_bookings', methods=['POST'])
@app.route('/api/bookings', methods=['POST'])
def book_lounge():
    data = request.json
    user_email = data.get('user_email')
    vendor_id = data.get('vendor_id')
    booking_date = data.get('booking_date')
    booking_time = data.get('booking_time')
    slots = data.get('slots', 1)

    if USE_SQLITE:
        booking = db.book_lounge(user_email, vendor_id, booking_date, booking_time, slots)
        if booking:
            return jsonify({"status": "success", "message": "Lounge booked successfully", "booking": booking})
        return jsonify({"status": "error", "message": "Failed to create booking"}), 500
    try:
        booking_resp = supabase.table('lounge_bookings').insert({
            'user_email': user_email,
            'vendor_id': vendor_id,
            'booking_date': booking_date,
            'booking_time': booking_time,
            'slots': slots,
            'status': 'Pending'
        }).execute()
        return jsonify({"status": "success", "message": "Lounge booked successfully", "booking": booking_resp.data[0]})
    except Exception as e:
        print("[FALLBACK] Supabase lounge booking error:", str(e))
        booking = db.book_lounge(user_email, vendor_id, booking_date, booking_time, slots)
        if booking:
            return jsonify({"status": "success", "message": "Lounge booked successfully", "booking": booking})
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/lounge_bookings/history', methods=['GET'])
@app.route('/api/bookings', methods=['GET'])
def lounge_booking_history():
    user_email = request.args.get('user_email') or request.args.get('email')
    if not user_email:
        return jsonify({"status": "error", "message": "Missing user_email parameter"}), 400
    if USE_SQLITE:
        return jsonify({"status": "success", "bookings": db.get_bookings(user_email)})
    try:
        bookings_resp = supabase.table('lounge_bookings').select('*').eq('user_email', user_email).order('id', desc=True).execute()
        bookings = bookings_resp.data or []
        for booking in bookings:
            v_resp = supabase.table('vendors').select('name', 'terminal', 'gate', 'image_url').eq('id', booking['vendor_id']).execute()
            if v_resp.data:
                booking['vendor_name'] = v_resp.data[0]['name']
                booking['terminal'] = v_resp.data[0]['terminal']
                booking['gate'] = v_resp.data[0]['gate']
                booking['image_url'] = v_resp.data[0]['image_url']
            else:
                booking['vendor_name'] = "Unknown Lounge"
                booking['terminal'] = "-"
                booking['gate'] = "-"
        return jsonify({"status": "success", "bookings": bookings})
    except Exception as e:
        print("[FALLBACK] Supabase booking history fetch error:", str(e))
        return jsonify({"status": "success", "bookings": db.get_bookings(user_email)})

# --- PARKING BOOKING SYSTEM ENDPOINTS ---

@app.route('/api/parking-bookings', methods=['POST'])
def book_parking():
    data = request.json
    user_email = data.get('user_email')
    zone = data.get('zone')
    hours = data.get('hours')
    plate_number = data.get('plate_number')
    payment_method = data.get('payment_method')
    total_price = data.get('total_price')

    booking = db.book_parking(user_email, zone, hours, plate_number, payment_method, total_price)
    if booking:
        return jsonify({"status": "success", "message": "Parking booked successfully", "booking": booking})
    return jsonify({"status": "error", "message": "Failed to book parking"}), 500

@app.route('/api/parking-bookings/history', methods=['GET'])
def parking_booking_history():
    user_email = request.args.get('user_email') or request.args.get('email')
    if not user_email:
        return jsonify({"status": "error", "message": "Missing user_email parameter"}), 400
    bookings = db.get_parking_bookings(user_email)
    return jsonify({"status": "success", "bookings": bookings})

# --- LOST AND FOUND ENDPOINTS ---

@app.route('/api/lost-items', methods=['GET'])
def get_lost_items():
    conn = db.get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM lost_items ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return jsonify({"status": "success", "items": [dict(row) for row in rows]})

@app.route('/api/lost-items', methods=['POST'])
def add_lost_item():
    data = request.json
    name = data.get('name')
    description = data.get('description')
    location = data.get('location')
    contact = data.get('contact')
    v_type = data.get('type', 'Lost')
    icon = data.get('icon', '📦')
    image = data.get('image')

    conn = db.get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO lost_items (name, description, location, contact, type, icon, image)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (name, description, location, contact, v_type, icon, image))
    conn.commit()
    conn.close()
@app.route('/api/lost-items/delete', methods=['POST'])
def delete_lost_item():
    data = request.json
    item_id = data.get('id')
    if not item_id:
        return jsonify({"status": "error", "message": "Missing item id"}), 400

    conn = db.get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM lost_items WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "message": "Item removed successfully"})

@app.route('/api/guides/<key>', methods=['GET'])
def get_guide_by_key(key):
    conn = db.get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM guides WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return jsonify({"status": "success", "guide": dict(row)})
    else:
        return jsonify({"status": "error", "message": "Guide not found"}), 404

# --- VENDOR MANAGEMENT ENDPOINTS ---

@app.route('/api/vendors/orders', methods=['GET'])
def get_vendor_orders():
    vendor_id = request.args.get('vendor_id')
    if not vendor_id:
        return jsonify({"status": "error", "message": "Missing vendor_id parameter"}), 400
    if USE_SQLITE:
        return jsonify({"status": "success", "orders": db.get_vendor_orders(vendor_id)})
    try:
        orders_resp = supabase.table('orders').select('*').eq('vendor_id', vendor_id).order('id', desc=True).execute()
        orders = orders_resp.data or []
        for order in orders:
            items_resp = supabase.table('order_items').select('*').eq('order_id', order['id']).execute()
            order['items'] = items_resp.data or []
        return jsonify({"status": "success", "orders": orders})
    except Exception as e:
        print("[FALLBACK] Supabase vendor orders fetch error:", str(e))
        return jsonify({"status": "success", "orders": db.get_vendor_orders(vendor_id)})

@app.route('/api/vendors/orders/<int:order_id>/status', methods=['POST'])
def update_order_status(order_id):
    data = request.json
    new_status = data.get('status')
    if USE_SQLITE:
        order = db.update_order_status(order_id, new_status)
        if order:
            return jsonify({"status": "success", "message": "Order status updated", "order": order})
        return jsonify({"status": "error", "message": "Order not found"}), 404
    try:
        response = supabase.table('orders').update({'status': new_status}).eq('id', order_id).execute()
        if response.data:
            return jsonify({"status": "success", "message": "Order status updated", "order": response.data[0]})
        return jsonify({"status": "error", "message": "Order not found"}), 404
    except Exception as e:
        print("[FALLBACK] Supabase update order status error:", str(e))
        order = db.update_order_status(order_id, new_status)
        if order:
            return jsonify({"status": "success", "message": "Order status updated", "order": order})
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/vendors/bookings', methods=['GET'])
def get_vendor_bookings():
    vendor_id = request.args.get('vendor_id')
    if not vendor_id:
        return jsonify({"status": "error", "message": "Missing vendor_id parameter"}), 400
    if USE_SQLITE:
        return jsonify({"status": "success", "bookings": db.get_vendor_bookings(vendor_id)})
    try:
        bookings_resp = supabase.table('lounge_bookings').select('*').eq('vendor_id', vendor_id).order('id', desc=True).execute()
        return jsonify({"status": "success", "bookings": bookings_resp.data or []})
    except Exception as e:
        print("[FALLBACK] Supabase vendor bookings fetch error:", str(e))
        return jsonify({"status": "success", "bookings": db.get_vendor_bookings(vendor_id)})

@app.route('/api/vendors/bookings/<int:booking_id>/status', methods=['POST'])
def update_booking_status(booking_id):
    data = request.json
    new_status = data.get('status')
    if USE_SQLITE:
        booking = db.update_booking_status(booking_id, new_status)
        if booking:
            return jsonify({"status": "success", "message": "Booking status updated", "booking": booking})
        return jsonify({"status": "error", "message": "Booking not found"}), 404
    try:
        response = supabase.table('lounge_bookings').update({'status': new_status}).eq('id', booking_id).execute()
        if response.data:
            return jsonify({"status": "success", "message": "Booking status updated", "booking": response.data[0]})
        return jsonify({"status": "error", "message": "Booking not found"}), 404
    except Exception as e:
        print("[FALLBACK] Supabase update booking status error:", str(e))
        booking = db.update_booking_status(booking_id, new_status)
        if booking:
            return jsonify({"status": "success", "message": "Booking status updated", "booking": booking})
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/vendors/products', methods=['GET', 'POST', 'PUT', 'DELETE'])
def manage_vendor_products():
    if request.method == 'GET':
        vendor_id = request.args.get('vendor_id')
        if not vendor_id:
            return jsonify({"status": "error", "message": "Missing vendor_id parameter"}), 400
        if USE_SQLITE:
            return jsonify({"status": "success", "products": db.get_products(vendor_id)})
        try:
            response = supabase.table('products').select('*').eq('vendor_id', vendor_id).execute()
            return jsonify({"status": "success", "products": response.data or []})
        except Exception as e:
            print("[FALLBACK] Supabase products query error:", str(e))
            return jsonify({"status": "success", "products": db.get_products(vendor_id)})

    elif request.method == 'POST':
        data = request.json
        if USE_SQLITE:
            product = db.add_product(
                data.get('vendor_id'),
                data.get('name'),
                data.get('price'),
                data.get('category'),
                data.get('description', ''),
                data.get('image_url', '')
            )
            return jsonify({"status": "success", "message": "Product added successfully", "product": product})
        try:
            ins_resp = supabase.table('products').insert({
                'vendor_id': data.get('vendor_id'),
                'name': data.get('name'),
                'price': data.get('price'),
                'rating': 5.0,
                'image_url': data.get('image_url', ''),
                'category': data.get('category'),
                'description': data.get('description', '')
            }).execute()
            return jsonify({"status": "success", "message": "Product added successfully", "product": ins_resp.data[0]})
        except Exception as e:
            print("[FALLBACK] Supabase product insert error:", str(e))
            product = db.add_product(
                data.get('vendor_id'),
                data.get('name'),
                data.get('price'),
                data.get('category'),
                data.get('description', ''),
                data.get('image_url', '')
            )
            return jsonify({"status": "success", "message": "Product added successfully", "product": product})

    elif request.method == 'PUT':
        data = request.json
        product_id = data.get('id')
        if USE_SQLITE:
            product = db.update_product(
                product_id,
                data.get('name'),
                data.get('price'),
                data.get('category'),
                data.get('description'),
                data.get('image_url')
            )
            return jsonify({"status": "success", "message": "Product updated successfully", "product": product})
        try:
            upd_resp = supabase.table('products').update({
                'name': data.get('name'),
                'price': data.get('price'),
                'category': data.get('category'),
                'description': data.get('description'),
                'image_url': data.get('image_url')
            }).eq('id', product_id).execute()
            return jsonify({"status": "success", "message": "Product updated successfully", "product": upd_resp.data[0]})
        except Exception as e:
            print("[FALLBACK] Supabase product update error:", str(e))
            product = db.update_product(
                product_id,
                data.get('name'),
                data.get('price'),
                data.get('category'),
                data.get('description'),
                data.get('image_url')
            )
            return jsonify({"status": "success", "message": "Product updated successfully", "product": product})

    elif request.method == 'DELETE':
        product_id = request.args.get('id')
        if USE_SQLITE:
            db.delete_product(product_id)
            return jsonify({"status": "success", "message": "Product deleted successfully"})
        try:
            supabase.table('products').delete().eq('id', product_id).execute()
            return jsonify({"status": "success", "message": "Product deleted successfully"})
        except Exception as e:
            print("[FALLBACK] Supabase product delete error:", str(e))
            db.delete_product(product_id)
            return jsonify({"status": "success", "message": "Product deleted successfully"})


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)

