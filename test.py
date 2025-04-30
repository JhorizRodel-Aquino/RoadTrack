def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            token = request.headers['Authorization'].split(" ")[1]
        
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        
        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            current_admin = Admin.query.filter_by(ID=data['admin_id']).first()
        except:
            return jsonify({'message': 'Token is invalid!'}), 401
        
        return f(current_admin, *args, **kwargs)
    
    return decorated

@app.route('/admin/signup', methods=['POST'])
def admin_signup():
    data = request.get_json()
    
    if not data or not data.get('email') or not data.get('password'):
        return jsonify({'message': 'Missing required fields'}), 400
    
    if Admin.query.filter_by(email=data['email']).first():
        return jsonify({'message': 'Email already exists'}), 400
    
    # Store password directly without hashing
    new_admin = Admin(email=data['email'], password_hash=data['password'])
    
    try:
        db.session.add(new_admin)
        db.session.commit()
        return jsonify({'message': 'Admin created successfully'}), 201
    except Exception as e:
        db.session.rollback()
        print(f"Error creating admin: {e}")
        return jsonify({'message': 'Error creating admin', 'error': str(e)}), 500

@app.route('/admin/login', methods=['POST'])
def admin_login():
    data = request.get_json()
    
    if not data or not data.get('email') or not data.get('password'):
        return jsonify({'message': 'Missing required fields'}), 400
    
    admin = Admin.query.filter_by(email=data['email']).first()
    
    if not admin:
        print(f"Login failed: Email {data['email']} not found")
        return jsonify({'message': 'Invalid email or password'}), 401
    
    # Check if the password matches directly without hashing
    if admin.password_hash != data['password']:
        print(f"Login failed: Invalid password for {data['email']}")
        return jsonify({'message': 'Invalid email or password'}), 401
    
    token = jwt.encode({
        'admin_id': admin.ID,
        'exp': datetime.utcnow() + timedelta(days=1)
    }, app.config['SECRET_KEY'])
    
    return jsonify({
        'message': 'Login successful',
        'token': token,
        'admin_id': admin.ID,
        'email': admin.email
    }), 200

@app.route('/admin/profile', methods=['GET'])
@token_required
def get_admin_profile(current_admin):
    return jsonify({
        'admin_id': current_admin.ID,
        'email': current_admin.email
    }), 200
