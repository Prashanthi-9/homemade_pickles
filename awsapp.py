import os
import uuid
from flask import Flask, render_template, request, redirect, session, url_for
import boto3
from botocore.exceptions import ClientError

# ---- Configuration ----
AWS_REGION = 'us-east-1'
SNS_TOPIC_ARN = os.getenv('SNS_TOPIC_ARN')  # set this in your environment variables

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET', 'supersecretkey')

# ---- AWS Resources ----
dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
sns = boto3.client('sns', region_name=AWS_REGION)

# ---- DynamoDB Tables ----
users_tbl = dynamodb.Table('pickles_users')
products_tbl = dynamodb.Table('pickles_products')
orders_tbl = dynamodb.Table('pickles_orders')

# ---- Routes ----

@app.route('/')
def home():
    if 'user' not in session:
        return redirect(url_for('login'))
    resp = products_tbl.scan()
    products = resp.get('Items', [])
    return render_template('index.html', products=products)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        try:
            users_tbl.put_item(
                Item={'username': username, 'password': password, 'is_admin': False},
                ConditionExpression='attribute_not_exists(username)'
            )
            return redirect(url_for('login'))
        except ClientError as e:
            if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                return "Username already taken"
            raise
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        resp = users_tbl.get_item(Key={'username': username})
        user = resp.get('Item')
        if user and user['password'] == password:
            session['user'] = username
            session['is_admin'] = user.get('is_admin', False)
            return redirect(url_for('home'))
        return "Invalid credentials"
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/add_to_cart/<pid>')
def add_to_cart(pid):
    if 'user' not in session:
        return redirect(url_for('login'))
    cart = session.get('cart', {})
    cart[pid] = cart.get(pid, 0) + 1
    session['cart'] = cart
    return redirect(url_for('cart'))

@app.route('/cart')
def cart():
    if 'user' not in session:
        return redirect(url_for('login'))
    items, total = [], 0
    for pid, qty in session.get('cart', {}).items():
        resp = products_tbl.get_item(Key={'product_id': pid})
        product = resp.get('Item')
        if product:
            items.append({'product': product, 'qty': qty})
            total += float(product['price']) * qty
    return render_template('cart.html', items=items, total=total)

@app.route('/checkout', methods=['POST'])
def checkout():
    if 'user' not in session:
        return redirect(url_for('login'))
    cart = session.get('cart', {})
    payment_method = request.form.get('payment_method')
    if not cart:
        return "Cart is empty"

    user = session['user']
    order_summary = []

    for pid, qty in cart.items():
        order_id = str(uuid.uuid4())
        orders_tbl.put_item(Item={
            'order_id': order_id,
            'user_id': user,
            'product_id': pid,
            'quantity': qty,
            'status': f"Confirmed ({payment_method})"
        })
        products_tbl.update_item(
            Key={'product_id': pid},
            UpdateExpression='SET quantity = quantity - :q',
            ExpressionAttributeValues={':q': qty}
        )
        # Get product info for SNS message
        product = products_tbl.get_item(Key={'product_id': pid}).get('Item', {})
        order_summary.append(f"{product.get('name', 'Unknown')} x {qty}")

    # Send SNS notification
    message = f"New order placed by {user}:\n" + "\n".join(order_summary)
    try:
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Message=message,
            Subject="New Pickles Order"
        )
    except ClientError as e:
        print("SNS Error:", e)

    session['cart'] = {}
    return render_template('success.html')

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        resp = users_tbl.get_item(Key={'username': username})
        user = resp.get('Item')
        if user and user.get('is_admin') and user['password'] == password:
            session['user'] = username
            session['is_admin'] = True
            return redirect(url_for('admin_dashboard'))
        return "Invalid admin credentials"
    return render_template('admin_login.html')

@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    return render_template('admin_dashboard.html')

@app.route('/admin/add', methods=['GET', 'POST'])
def admin_add_product():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    if request.method == 'POST':
        pid = str(uuid.uuid4())
        name = request.form['name']
        price = float(request.form['price'])
        qty = int(request.form['quantity'])
        img = request.form.get('image') or '/static/images/default.jpg'
        products_tbl.put_item(Item={
            'product_id': pid,
            'name': name,
            'price': price,
            'quantity': qty,
            'image': img
        })
        return redirect(url_for('admin_dashboard'))
    return render_template('admin_add.html')

@app.route('/admin/stock')
def admin_stock():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    resp = products_tbl.scan()
    return render_template('admin_stock.html', products=resp.get('Items', []))

@app.route('/admin/orders')
def admin_orders():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    resp = orders_tbl.scan()
    orders = []
    for o in resp.get('Items', []):
        u = users_tbl.get_item(Key={'username': o['user_id']}).get('Item', {})
        p = products_tbl.get_item(Key={'product_id': o['product_id']}).get('Item', {})
        orders.append({
            'id': o['order_id'],
            'username': u.get('username', '?'),
            'product_name': p.get('name', '?'),
            'quantity': o['quantity'],
            'status': o['status']
        })
    return render_template('admin_orders.html', orders=orders)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
