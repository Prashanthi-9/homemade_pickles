from flask import Flask, render_template, request, redirect, session, url_for
import sqlite3, os

app = Flask(__name__)
app.secret_key = 'pickle_secret'
DB = 'database.db'

def init_db():
    with sqlite3.connect(DB) as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            is_admin INTEGER DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, price REAL, quantity INTEGER, image TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, product_id INTEGER, quantity INTEGER, status TEXT)''')

        # ✅ Create default admin if not exists
        admin = c.execute("SELECT * FROM users WHERE username='admin'").fetchone()
        if not admin:
            c.execute("INSERT INTO users (username, password, is_admin) VALUES (?, ?, ?)",
                      ('admin', 'admin123', 1))

        conn.commit()

@app.route('/')
def home():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    with sqlite3.connect(DB) as conn:
        products = conn.execute("SELECT * FROM products").fetchall()
    return render_template('index.html', products=products)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username, password = request.form['username'], request.form['password']
        with sqlite3.connect(DB) as conn:
            try:
                conn.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
                conn.commit()
                return redirect(url_for('login'))
            except sqlite3.IntegrityError:
                return "Username already taken"
    return render_template('register.html')
@app.route('/checkout', methods=['POST'])
def checkout():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    uid = session['user_id']
    cart = session.get('cart', {})
    payment_method = request.form.get('payment_method')

    if not cart:
        return "Cart is empty"

    with sqlite3.connect(DB) as conn:
        for pid, qty in cart.items():
            conn.execute("INSERT INTO orders (user_id, product_id, quantity, status) VALUES (?, ?, ?, ?)",
                         (uid, pid, qty, f"Confirmed ({payment_method})"))
            conn.execute("UPDATE products SET quantity = quantity - ? WHERE id = ?", (qty, pid))
        conn.commit()

    session['cart'] = {}
    return render_template('success.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username, password = request.form['username'], request.form['password']
        with sqlite3.connect(DB) as conn:
            user = conn.execute("SELECT * FROM users WHERE username=? AND password=?", (username, password)).fetchone()
            if user:
                session['user_id'] = user[0]
                session['username'] = user[1]
                return redirect(url_for('home'))
            else:
                return "Invalid credentials"
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/add_to_cart/<int:pid>')
def add_to_cart(pid):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    cart = session.get('cart', {})
    cart[str(pid)] = cart.get(str(pid), 0) + 1
    session['cart'] = cart
    return redirect(url_for('cart'))

@app.route('/cart')
def cart():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    items, total = [], 0
    with sqlite3.connect(DB) as conn:
        for pid, qty in session.get('cart', {}).items():
            product = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
            if product:
                items.append((product, qty))
                total += product[2] * qty
    return render_template('cart.html', items=items, total=total)

# === Admin Section ===

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        with sqlite3.connect(DB) as conn:
            user = conn.execute("SELECT * FROM users WHERE username=? AND password=? AND is_admin=1", (username, password)).fetchone()
            if user:
                session['admin_id'] = user[0]
                session['admin_username'] = user[1]
                return redirect(url_for('admin_dashboard'))
        return "Invalid admin credentials"
    return render_template('admin_login.html')

@app.route('/admin/dashboard')
def admin_dashboard():
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))
    return render_template('admin_dashboard.html')

@app.route('/admin/add', methods=['GET', 'POST'])
def admin_add_product():
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))
    if request.method == 'POST':
        name = request.form['name']
        price = float(request.form['price'])
        quantity = int(request.form['quantity'])
        image = request.form['image'] or '/static/images/pickle1.jpg'
        with sqlite3.connect(DB) as conn:
            conn.execute("INSERT INTO products (name, price, quantity, image) VALUES (?, ?, ?, ?)",
                         (name, price, quantity, image))
            conn.commit()
        return redirect(url_for('admin_dashboard'))
    return render_template('admin_add.html')

@app.route('/admin/stock')
def admin_stock():
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))
    with sqlite3.connect(DB) as conn:
        products = conn.execute("SELECT * FROM products").fetchall()
    return render_template('admin_stock.html', products=products)

@app.route('/admin/orders')
def admin_orders():
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))
    with sqlite3.connect(DB) as conn:
        orders = conn.execute('''
            SELECT o.id, u.username, p.name, o.quantity, o.status
            FROM orders o
            JOIN users u ON o.user_id = u.id
            JOIN products p ON o.product_id = p.id
        ''').fetchall()
    return render_template('admin_orders.html', orders=orders)

if __name__ == '__main__':
    if not os.path.exists(DB):
        init_db()
        with sqlite3.connect(DB) as conn:
            conn.execute("INSERT INTO products (name, price, quantity, image) VALUES (?, ?, ?, ?)",
                         ('Mango Pickle', 150, 20, '/static/images/mango.jpg'))
            conn.execute("INSERT INTO products (name, price, quantity, image) VALUES (?, ?, ?, ?)",
                         ('Lemon Pickle', 120, 15, '/static/images/lemon.jpg'))
            conn.commit()
    else:
        init_db()  # ensure tables exist even if DB file exists
    app.run(debug=True)
