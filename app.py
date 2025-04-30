from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timedelta
import requests
import time
import threading
from threading import Event
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import os
import re


import hashlib
from flask_bcrypt import Bcrypt
import jwt
from functools import wraps

app = Flask(__name__)

# JWT Configuration
app.config['SECRET_KEY'] = '68e8bcea7bb8b8d1c48987cc'  # Secure random key

CORS(app)

geocode_event = Event()

# MySQL Database Configuration
# hostname = 'localhost'
# username = 'root'
# password = ''
# dbname = 'roadtrackdb'
# hostname = 'srv1668.hstgr.io'
# username = 'u854837124_roadtrack'
# password = 'RoadTrack123!'
# dbname = 'u854837124_roadtrackdb'
# hostname = 'localhost'
# username = 'jhoriz'
# password = 'jrfa2202!sql'
# dbname = 'arcdem_db'
# hostname = '157.230.248.185'
# username = 'jhoriz'
# password = 'jrfa2202!sql'
# dbname = 'arcdem_db'
hostname = 'localhost'
username = 'root'
password = ''
dbname = 'arcdem_db'


ALLOWED_EXTENSIONS = {'jpg', 'jpeg'}
app.config['UPLOAD_FOLDER'] = 'uploads' # Set the path to the 'uploads' directory
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)  # Create the 'uploads' folder if it doesn't exist

app.config['SQLALCHEMY_DATABASE_URI'] = f'mysql+pymysql://{username}:{password}@{hostname}/{dbname}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 30
}

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)


class Group(db.Model):
    ID = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    mutable = db.Column(db.Boolean, default=True)
    parent_ID = db.Column(db.Integer, db.ForeignKey('group.ID'))
    assessments = db.relationship('Assessment', backref='group', lazy=True)
    children = db.relationship('Group', backref=db.backref('parent', remote_side=[ID]), lazy=True)

    def get_all_assessments(self):
        """
        Recursively fetch all assessments for this group and its child groups,
        sorted by the datetime embedded in the filename.
        """

        def extract_datetime_from_filename(filename):
            match = re.match(r"(\d{8})_(\d{6})", filename)
            if match:
                return datetime.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M%S")
            return datetime.min

        # Fetch and combine
        assessments = list(self.assessments)
        for child in self.children:
            assessments += child.get_all_assessments()

        # Sort before returning
        return sorted(assessments, key=lambda a: extract_datetime_from_filename(a.filename), reverse=True)

    def to_dict(self):
        return {
            'id': self.ID,
            'name': self.name,
            'parent_id': self.parent_ID,
        }

    def info_to_dict(self):
        return {
            'name': self.name,
            'n_assess': len(self.get_all_assessments()),
            'n_cracks': self.total_cracks(),
            'date': self.latest_assessment_date(),
            'parent_id': self.parent_ID
        }

    def assessments_to_dict(self):
        return {'assessments': [assessment.to_dict() for assessment in self.get_all_assessments()]}

    def children_to_dict(self):
        return {'children': [child.to_dict() for child in self.children]}

    def summary_to_dict(self):
        assessments = [{**assessment.to_dict(), **assessment.cracks_to_dict()} \
            for assessment in self.get_all_assessments()]

        address = ", ".join(ancestor['name'] for ancestor in self.ancestors_to_dict())

        return {
            'name': self.name,
            'n_assess': len(self.get_all_assessments()),
            'n_cracks': self.total_cracks(),
            'date': self.latest_assessment_date(),
            'assessments': assessments,
            'address': address
        }

    def ancestors_to_dict(self):
        parents = []
        curr_grp = self
        parents.append({'name': curr_grp.name, 'id': curr_grp.ID})

        while curr_grp and curr_grp.parent_ID is not None:
            curr_grp = db.session.get(Group, curr_grp.parent_ID)
            if curr_grp:
                parents.append({'name': curr_grp.name, 'id': curr_grp.ID})

        return parents

    def descendants_to_dict(self):
        def build_hierarchy(group):
            return {
                'name': group.name,
                'id': group.ID,
                'children': [build_hierarchy(child) for child in group.children]
            }

        return build_hierarchy(self)

    def alldescendants_to_dict(self):
        def extract_datetime_from_filename(filename):
            match = re.match(r"(\d{8})_(\d{6})", filename)
            if match:
                return datetime.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M%S")
            return datetime.min
        def build_hierarchy(group):
            sorted_assessments = sorted(
                group.assessments,
                key=lambda a: extract_datetime_from_filename(a.filename),
                reverse=True 
            )
            return {
                'id': group.ID,
                'name': group.name,
                'children': [build_hierarchy(child) for child in group.children],
                **({'assessments': [a.to_dict() for a in sorted_assessments]} if group.assessments else {})
            }

        return build_hierarchy(self)

    def total_cracks(self):
        total = {
            'longi': 0,
            'trans': 0,
            'multi': 0
        }

        for assessment in self.get_all_assessments():
            cracks_count = assessment.count_cracks()

            total['longi'] += cracks_count['longi']
            total['trans'] += cracks_count['trans']
            total['multi'] += cracks_count['multi']

        return total

    def latest_assessment_date(self):
        if not self.get_all_assessments():
            return ""
        return str(max(assessment.date for assessment in self.get_all_assessments() if assessment.date))

class Assessment(db.Model):
    ID = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(100), nullable=False)
    start_lat = db.Column(db.Numeric(9,7), nullable=False)   # FIX: Use Numeric(9,7)
    start_lon = db.Column(db.Numeric(10,7), nullable=False)  # FIX: Use Numeric(10,7)
    end_lat = db.Column(db.Numeric(9,7), nullable=False)     # FIX: Use Numeric(9,7)
    end_lon = db.Column(db.Numeric(10,7), nullable=False)    # FIX: Use Numeric(10,7)
    date = db.Column(db.DateTime, nullable=False)
    needs_geocoding = db.Column(db.Boolean, default=True)
    group_ID = db.Column(db.Integer, db.ForeignKey('group.ID'))
    cracks = db.relationship('Crack', backref='assessment', lazy=True)

    def __repr__(self):
        return f'Assessment {self.ID}'

    def to_dict(self):
        return {
            'id': self.ID,
            'start_coor': (float(self.start_lat), float(self.start_lon)),
            'end_coor': (float(self.end_lat), float(self.end_lon))
        }

    def cracks_to_dict(self):
        return {
            'filename': self.filename,
            'date': self.date,
            'cracks': [crack.to_dict() for crack in self.cracks]
        }

    def count_cracks(self):
        counts = {
            'longi': 0,
            'trans': 0,
            'multi': 0
        }
        for crack in self.cracks:
            crack_type = crack.crack_type.lower()
            if crack_type == 'longitudinal':
                counts['longi'] += 1
            elif crack_type == 'transverse':
                counts['trans'] += 1
            elif crack_type == 'multiple':
                counts['multi'] += 1

        return counts

    def address_to_dict(self):
        return self.group.ancestors_to_dict()

class Crack(db.Model):
    ID = db.Column(db.Integer, primary_key=True)
    crack_type = db.Column(db.String(15), nullable=False)
    crack_severity = db.Column(db.String(10), nullable=False)
    crack_length = db.Column(db.Numeric(4,3), nullable=False)
    crack_width = db.Column(db.Numeric(4,3))
    index = db.Column(db.Integer, nullable=False)
    assessment_ID = db.Column(db.Integer, db.ForeignKey('assessment.ID'))

    def __repr__(self):
        return f'Crack {self.ID} under Assessment {self.assessment_ID}'

    def to_dict(self):
        return {
            'id': self.ID,
            'crack_type': self.crack_type,
            'crack_severity': self.crack_severity,
            'crack_length': self.crack_length,
            'crack_width': self.crack_width,
            'index': self.index,
            'assessment_id': self.assessment_ID
        }

class Admin(db.Model):
    ID = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(30), nullable=False, unique=True)
    email = db.Column(db.String(50), nullable=False, unique=True)
    password_hash = db.Column(db.String(60), nullable=False)
    created = db.Column(db.DateTime, default=datetime.utcnow)  # Track account creation date
    status = db.Column(db.String(20), default='Pending')  # Track the status of the admin account (active, suspended, etc.)
    
    @property
    def password(self):
        return self.password

    @password.setter
    def password(self, plain_text_password):
        self.password_hash = bcrypt.generate_password_hash(plain_text_password).decode('utf-8')
        
    @property
    def gravatar_url(self):
        return self.get_gravatar_url(self.email)  # Generate Gravatar URL based on email

    def get_gravatar_url(self, email, size=200):
        # Normalize the email by stripping leading/trailing spaces and converting to lowercase
        normalized_email = email.strip().lower()
        
        # Create an MD5 hash of the email
        email_hash = hashlib.md5(normalized_email.encode('utf-8')).hexdigest()
        
        # Construct the Gravatar URL
        url = f"https://www.gravatar.com/avatar/{email_hash}?s={size}&d=identicon"  # `d=identicon` will give a default image if no Gravatar is set
        
        return url
        
    def check_password_correction(self, attempted_password):
        return bcrypt.check_password_hash(self.password_hash, attempted_password)

    def to_dict(self):
        return {'id': self.ID, "username": self.username, "email": self.email, 'status': self.status, 'filename': self.gravatar_url}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def request_geocode(lat, lon):
    url = "https://nominatim.openstreetmap.org/reverse"
    params = {
        "lat": lat,
        "lon": lon,
        "format": "json",
        "addressdetails": 1
    }
    headers = {
        "User-Agent": "ARCDEM-GIS-WebApp/1.0 (jhorizrodel.aquino@cvsu.edu.ph)"  # Required by Nominatim
    }

    response = requests.get(url, params=params, headers=headers)
    data = response.json()

    time.sleep(1)

    address = data.get("address", {})

    result = {
        "city": address.get("city") or address.get("town") or address.get("municipality") or "no city",
        "province": address.get("state") or "no province",
        "region": address.get("region") or "no region",
    }

    return result

def reverse_geocode(assessment):

    lat = (assessment.start_lat + assessment.end_lat) / 2
    lon = (assessment.start_lon + assessment.end_lon) / 2
    location = request_geocode(lat, lon)

    region = location['region']
    province = location['province']
    city = location['city']

    # Region group
    reg_group = Group.query.filter_by(name=region).first()
    if not reg_group:
        reg_group = Group(name=region, mutable=False)
        db.session.add(reg_group)
        db.session.flush()

    # Province group
    prov_group = Group.query.filter_by(name=province, parent_ID=reg_group.ID).first()
    if not prov_group:
        prov_group = Group(name=province, mutable=False, parent=reg_group)
        db.session.add(prov_group)
        db.session.flush()

    # City group
    city_group = Group.query.filter_by(name=city, parent_ID=prov_group.ID).first()
    if not city_group:
        city_group = Group(name=city, mutable=False, parent=prov_group)
        db.session.add(city_group)
        db.session.flush()

    # Assign assessment to city group
    assessment.group = city_group
    assessment.needs_geocoding = False

def geocoding_worker():
    print("Geocoding worker started...")
    while True:
        with app.app_context():
            failed_assessments = Assessment.query.filter_by(needs_geocoding=True).all()

            if not failed_assessments:
                geocode_event.wait(timeout=30)
                geocode_event.clear()  # Reset the event
                continue

            for assessment in failed_assessments:
                try:
                    reverse_geocode(assessment)
                    assessment.needs_geocoding = False
                    print(f"Geocoded assessment {assessment.ID}")
                except Exception as e:
                    print(f"Geocoding failed for {assessment.ID}: {e}")

            db.session.commit()
            print("Batch commit done.")
            time.sleep(5)  # small delay before next check

def create_initial_admin():
    # Check if any admin already exists
    if Admin.query.first() is None:
        default_admin = Admin(
            username="admin",
            email="arcdem.moderator@gmail.com",
            status="Super Admin",
            password = "arcdem2025!"
        )

        db.session.add(default_admin)
        db.session.commit()

        print("Initial Super Admin created successfully!")
    else:
        print("Admin already exists, skipping initial creation.")

def extract_datetime_from_filename(filename):
    try:
        # Example filename: 20250417_170535-14_196527-120_881195-14_196555-120_881187
        match = re.match(r"(\d{8})_(\d{6})", filename)
        if match:
            date_str = match.group(1) + match.group(2)  # "20250417" + "170535"
            return datetime.datetime.strptime(date_str, "%Y%m%d%H%M%S")
    except Exception as e:
        pass
    return datetime.min  # Use minimum datetime if parsing fails


# Create database tables
with app.app_context():
    db.create_all()
    create_initial_admin()


@app.route('/signup', methods=['POST'])
def signup():
    if request.content_type != 'application/json':
        return jsonify({"response": "Invalid Content-Type. Expected application/json"}), 400

    try:
        admin = request.get_json()

        username = admin.get("username")
        email=admin.get('email')
        password=admin.get('password')

        if not all([username, email, password]):
                return jsonify({"response": "Missing required fields"}), 400

        new_admin = Admin(username=username, email=email, password=password)
        
        db.session.add(new_admin)
        db.session.commit()

        return jsonify({"response": "Signed up successfully!"}), 200

    except SQLAlchemyError as e:
        db.session.rollback()
        return jsonify({"response": f"Database error: {str(e)}"}), 500

    except Exception as e:
        return jsonify({"response": f"Something went wrong: {str(e)}"}), 500

@app.route('/login', methods=['POST'])
def login():
    if request.content_type != 'application/json':
        return jsonify({"response": "Invalid Content-Type. Expected application/json"}), 400

    try:
        admin = request.get_json()

        email_or_username = admin.get("emailOrUsername")
        password = admin.get('password')

        if not all([email_or_username, password]):
            return jsonify({"response": "Missing required fields"}), 400

        if "@" in email_or_username:
            email = email_or_username
            attempted_admin = Admin.query.filter_by(email=email).first()
        else:
            username = email_or_username
            attempted_admin = Admin.query.filter_by(username=username).first()

        if attempted_admin is None or not attempted_admin.check_password_correction(attempted_password=password):
            return jsonify({"response": "Incorrect username, email or password."}), 401

        if attempted_admin.status == "Pending":
            return jsonify({"response": "This account is still awaiting approval from the administrator. Please check your email regularly for updates."}), 403
        
        if attempted_admin.status == "Rejected":
            return jsonify({"response": "This account is rejected by the administrator."}), 403

        # Generate JWT token
        # expiration = datetime.utcnow() + timedelta(minutes=5)
        expiration = datetime.utcnow() + timedelta(hours=1)
        token = jwt.encode({"admin_id": attempted_admin.ID, "exp": expiration}, app.config['SECRET_KEY'], algorithm="HS256")

        return jsonify({
            "response": "Logged in successfully!",
            "token": token
        }), 200

    except SQLAlchemyError as e:
        db.session.rollback()
        return jsonify({"response": f"Database error: {str(e)}"}), 500

    except Exception as e:
        return jsonify({"response": f"Something went wrong: {str(e)}"}), 500

@app.route('/authenticate', methods=['GET'])
def authenticate():
    token = request.headers.get('Authorization')  # Get token from Authorization header

    if not token:
        return jsonify({"response": "Token missing. Please provide a valid token in the Authorization header."}), 401

    # Ensure the token starts with "Bearer " (if you're following common token formats)
    if token.startswith('Bearer '):
        token = token[7:]  # Remove "Bearer " prefix from token
    else:
        return jsonify({"response": "Invalid token format. Token should start with 'Bearer '."}), 400

    # Call the validate function to decode and validate the token
    validation_result = validate_token(token)
    if validation_result["status_code"] != 200:
        return jsonify(validation_result), validation_result["status_code"]

    return jsonify({"response": "Welcome to the admin page!"}), 200

def validate_token(token):
    try:
        # Decoding the token to check its validity
        decoded_token = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
        return {"status_code": 200, "decoded_token": decoded_token}
    except jwt.ExpiredSignatureError:
        return {"response": "Invalid or expired token", "status_code": 401}
    except jwt.InvalidTokenError:
        return {"response": "Invalid or expired token", "status_code": 401}
    except Exception as e:
        return {"response": f"Error: {str(e)}", "status_code": 400}

def token_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.headers.get('Authorization')

        current_admin = None
        if token:
            try:
                # Extract token from the "Bearer <token>" format
                token = token.split(" ")[1]  # Assuming the token is in the format "Bearer <token>"

                # Call validate_jwt_token to check if the token is valid
                validation_result = validate_token(token)
                if validation_result["status_code"] != 200:
                    return jsonify(validation_result), validation_result["status_code"]

                current_admin = db.session.get(Admin, validation_result["decoded_token"]['admin_id'])
                if not current_admin:
                    return jsonify({"response": "Admin not found"}), 404

            except Exception as e:
                return jsonify({"response": f"Error: {str(e)}"}), 401

        return f(current_admin, *args, **kwargs)

    return decorated_function


@app.route('/profile', methods=['GET'])
@token_required
def get_admin_profile(current_admin):
    return jsonify({
        'id': current_admin.ID,
        'username': current_admin.username,
        'email': current_admin.email,
        'filename': current_admin.gravatar_url
    }), 200

@app.route('/admins', methods=['GET'])
@token_required
def get_admins(current_admin):
    admins = Admin.query.all()

    if not admins:
        return jsonify({"error": "No admins found."}), 404

    return jsonify([admin.to_dict() for admin in admins]), 200
    
@app.route('/admin/<int:ID>', methods=['PATCH'])
@token_required
def update_admin_status(current_admin, ID):
    admin = db.session.get(Admin, ID)

    if not admin:
        return jsonify({"error": f"Admin with ID {ID} is not found."}), 404

    try:
        new_status = request.get_json()
        admin.status = new_status['statusUpdate']
        
        db.session.commit()

        return jsonify({"response": f"Admin with ID {ID} is updated successfully."}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Failed to update admin. Error: {str(e)}"}), 500

@app.route('/admin/<int:ID>', methods=['DELETE'])
@token_required
def delete_admin(current_admin, ID):
    admin = db.session.get(Admin, ID)

    if not admin:
        return jsonify({"error": f"Admin with ID {ID} is not found."}), 404

    db.session.delete(admin)
    db.session.commit()

    return jsonify({"response": f"Admin with ID {ID} is removed successfully."}), 200
    
 
@app.route('/')
def home():
    return "Hello World! RoadTrack Backend is Up!"

@app.route('/update_logs', methods=['POST'])
def update_logs():
    if request.content_type != 'application/json':
        return jsonify({"response": "Invalid Content-Type. Expected application/json"}), 400

    try:
        assessments = request.get_json()

        for assessment in assessments:
            # Extract required fields
            filename = assessment.get("filename")
            start_lat = assessment.get("start_coor")[0]
            start_lon = assessment.get("start_coor")[1]
            end_lat = assessment.get("end_coor")[0]
            end_lon = assessment.get("end_coor")[1]
            date_created = assessment.get("date_created")
            cracks = assessment.get("cracks")

            # Validate required fields
            if not all([filename, start_lat, start_lon, end_lat, end_lon, date_created, cracks]):
                return jsonify({"response": "Missing required fields"}), 400

            # Save to the database
            new_assessment = Assessment(
                filename=filename,
                start_lat=start_lat,
                start_lon=start_lon,
                end_lat=end_lat,
                end_lon=end_lon,
                date=datetime.strptime(date_created, "%Y%m%d_%H-%M-%S")
            )
            db.session.add(new_assessment)
            db.session.flush()  # Get `ID` before committing

            for crack in cracks:
                # Check if width is not None or null before adding it
                # Check if width is not None and not 0 before adding it
                crack_width = crack.get("width") if crack.get("width") not in [None, 0] else None

                new_crack = Crack(
                    assessment_ID=new_assessment.ID,
                    crack_type=crack["type"],
                    crack_severity=crack["severity"],
                    crack_length=crack["length"],
                    crack_width=crack_width,  # Only add width if it's not null
                    index=crack['index']
                )
                db.session.add(new_crack)

        db.session.commit()
        geocode_event.set()  # Wake the geocoding worker immediately
        return jsonify({"response": "Logs updated successfully!"}), 200

    except SQLAlchemyError as e:
        db.session.rollback()
        return jsonify({"response": f"Database error: {str(e)}"}), 500

    except Exception as e:
        return jsonify({"response": f"Something went wrong: {str(e)}"}), 500

@app.route('/upload', methods=['POST'])
def upload_files():
    if 'file' not in request.files:
        return jsonify({"error": "No files found in request"}), 400

    # We expect a single file at a time (so we use getlist to capture all "file" keys if there are any)
    files = request.files.getlist('file')  # Get the list of files under the "file" key
    uploaded_files = []

    for file in files:
        if file and allowed_file(file.filename):
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
            file.save(file_path)
            uploaded_files.append(file.filename)

    if not uploaded_files:
        return jsonify({"error": "No valid files uploaded. Only JPG or JPEG are allowed."}), 400

    return jsonify({"message": "Files uploaded successfully!", "uploaded_files": uploaded_files}), 200

@app.route('/view_logs', methods=['GET'])
def view_logs():
    assessments = Assessment.query.all()
    query = [{**assessment.to_dict(), **assessment.cracks_to_dict()} for assessment in assessments]
    return jsonify(query), 200

@app.route('/ping', methods=['GET'])
def ping():
    cracks = Crack.query.all()
    result = [crack.to_dict() for crack in cracks]
    return jsonify(result), 200

@app.route('/group/<string:level>')
def get_groups(level):
    if level == "region":
        groups = Group.query.filter_by(parent_ID=None).all()
    elif level == "province":
        regions = Group.query.filter_by(parent_ID=None).all()
        groups = []

        for region in regions:
            groups.extend(region.children)
    elif level == "city":
        regions = Group.query.filter_by(parent_ID=None).all()
        provinces = []

        for region in regions:
            provinces.extend(region.children)

        groups = []
        for province in provinces:
            groups.extend(province.children)
    else:
        return jsonify({"error": "Invalid parameter level"}), 400

    query = [group.to_dict() for group in groups]
    return jsonify(query), 200

@app.route('/group/<int:ID>', methods=['GET'])
@token_required
def get_group(current_admin, ID):

    group = db.session.get(Group, ID)

    if not group:
        return jsonify({"error": f"Group with the id {ID} is not found"}), 404

    return jsonify(group.info_to_dict()), 200

@app.route('/group/<int:ID>/children', methods=['GET'])
def get_group_children(ID):
    group = db.session.get(Group, ID)

    if not group:
        return jsonify({"error": f"Group with ID {ID} is not found."}), 404

    return jsonify(group.children_to_dict()), 200

@app.route('/group/<int:ID>/descendants', methods=['GET'])
def get_group_descendants(ID):
    group = db.session.get(Group, ID)

    if not group:
        return jsonify({"error": f"Group with ID {ID} is not found."}), 404

    return jsonify(group.descendants_to_dict()), 200

@app.route('/group/descendants', methods=['GET'])
@token_required
def get_groups_descendants(current_admin):
    groups = Group.query.filter_by(parent_ID=None).all()

    if not groups:
        return jsonify({"error": "No top-level groups found."}), 404

    return jsonify([group.alldescendants_to_dict() for group in groups]), 200

@app.route('/group/<int:ID>/ancestors', methods=['GET'])
def get_group_ancestors(ID):
    group = db.session.get(Group, ID)

    if not group:
        return jsonify({"error": f"Group with ID {ID} is not found."}), 404

    return jsonify(group.ancestors_to_dict()), 200

@app.route('/group/<int:ID>/summary', methods=['GET'])
def get_group_summary(ID):
    group = db.session.get(Group, ID)

    if not group:
        return jsonify({"error": f"Group with ID {ID} is not found."}), 404

    return jsonify(group.summary_to_dict()), 200

@app.route('/group/<int:ID>/assessments', methods=['GET'])
@token_required
def get_group_assessments(current_admin, ID):
    group = db.session.get(Group, ID)

    if not group:
        return jsonify({"error": f"Group with ID {ID} is not found."}), 404

    return jsonify(group.assessments_to_dict()), 200

@app.route('/assessments', methods=['GET'])
@token_required
def get_assessments(current_admin):
    assessments = Assessment.query.all()

    if not assessments:
            return jsonify({"error": f"No assessments found."}), 404

        # Sort by extracted datetime from filename
    sorted_assessments = sorted(
        assessments,
        key=lambda a: extract_datetime_from_filename(a.filename),
        reverse=True  # change to True for newest first
    )

    return jsonify([assessment.to_dict() for assessment in sorted_assessments])

@app.route('/assessment/<int:ID>/cracks', methods=['GET'])
@token_required
def get_assessment_cracks(current_admin, ID):
    assessment = db.session.get(Assessment, ID)

    if not assessment:
        return jsonify({"error": f"Assessment with ID {ID} is not found."}), 404

    return jsonify(assessment.cracks_to_dict())

@app.route('/assessment/<int:ID>/address', methods=['GET'])
def get_assessment_address(ID):
    assessment = db.session.get(Assessment, ID)

    if not assessment:
        return jsonify({"error": f"Assessment with ID {ID} is not found."}), 404

    return jsonify(assessment.address_to_dict())

@app.route('/image/<path:filename>', methods=['GET'])
def get_image(filename):
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

    if not os.path.isfile(file_path):
        return "File not found", 404
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename), 200

@app.route('/cracks', methods=['GET'])
def get_cracks():
    cracks = Crack.query.all()

    if not cracks:
            return jsonify({"error": f"No cracks found."}), 404

    # Return the data as a JSON response
    return jsonify([crack.to_dict() for crack in cracks])

def get_all_subgroups(group):
    """Recursively get all subgroups of a group"""
    subgroups = []
    for child in group.children:
        subgroups.append(child)
        subgroups.extend(get_all_subgroups(child))
    return subgroups

def get_all_assessments_in_group(group):
    """Get all assessments in a group and its subgroups"""
    assessments = list(group.assessments)  # Start with assessments in this group
    
    # Add assessments from all subgroups
    for child in group.children:
        assessments.extend(get_all_assessments_in_group(child))
    
    return assessments

def check_and_delete_empty_ancestors(group):
    """
    Recursively checks and deletes empty ancestor groups.
    A group is deleted if it has no remaining assessments and no child groups.
    """
    while group:
        # Check if the group has any remaining assessments or child groups
        has_assessments = db.session.query(Assessment).filter_by(group_ID=group.ID).first() is not None
        has_children = db.session.query(Group).filter_by(parent_ID=group.ID).first() is not None

        if not has_assessments and not has_children:
            parent = group.parent  # Save reference to parent before deleting
            db.session.delete(group)
            db.session.commit()
            group = parent  # Move to the parent group for further checking
        else:
            break  # Stop recursion if the group is not empty


@app.route('/average_crack_length/leaf_groups', methods=['GET'])
def average_crack_length_leaf_groups():
    all_groups = Group.query.all()
    leaf_groups = [group for group in all_groups if not group.children]

    result = {}

    for group in leaf_groups:
        assessments = group.assessments

        if not assessments:
            avg_crack_length = 0.0
        else:
            total_crack_length = sum(
                float(crack.crack_length)
                for assessment in assessments
                for crack in assessment.cracks
            )
            avg_crack_length = total_crack_length / len(assessments)

        result[group.ID] = {
            'group_name': group.name,
            'average_crack_length': round(avg_crack_length, 3)
        }

    return jsonify(result)

@app.route('/priority_scores')
def priority_scores():
    groups = Group.query.all()
    data = []

    for group in groups:
        if not group.children:  # innermost groups only
            total_crack_score = 0
            total_assessments = len(group.get_all_assessments())

            for assessment in group.get_all_assessments():
                for crack in assessment.cracks:
                    if crack.crack_severity.lower() == 'wide':
                        total_crack_score += float(crack.crack_length) * 0.7
                    elif crack.crack_severity.lower() == 'narrow':
                        total_crack_score += float(crack.crack_length) * 0.3

            if total_assessments > 0:
                total_assessment_length = total_assessments * 5  # 5m each
                score_per_meter = total_crack_score / total_assessment_length
            else:
                score_per_meter = 0

            data.append({
                'group_id': group.ID,
                'group_name': group.name,
                'weighted_crack_score_per_meter': round(score_per_meter, 2)
            })

    return jsonify(data)

@app.route('/group', methods=['POST'])
@token_required
def create_group(current_admin):
    data = request.get_json()

    name = data.get('name')
    group_ids = data.get('groups', [])
    assessment_ids = data.get('assessments', [])

    if not name:
        return jsonify({'error': 'Group name is required'}), 400

    if not group_ids and not assessment_ids:
        return jsonify({'error': 'No groups or assessments provided'}), 400

    groups = [db.session.get(Group, gid) for gid in group_ids]
    assessments = [db.session.get(Assessment, aid) for aid in assessment_ids]

    if any(g is None for g in groups):
        return jsonify({'error': 'One or more groups not found'}), 404
    if any(a is None for a in assessments):
        return jsonify({'error': 'One or more assessments not found'}), 404

    # Check if group with same name already exists
    existing_group = Group.query.filter_by(name=name).first()

    if existing_group:
        target_group = existing_group
    else:
        # Determine parent ID based on context
        parent_id = None
        if group_ids:
            parent_ids = set(g.parent_ID for g in groups)
            parent_id = parent_ids.pop() if len(parent_ids) == 1 else None
        elif assessment_ids:
            parent_ids = set(a.group_ID for a in assessments)
            if len(parent_ids) > 1:
                return jsonify({'error': 'All assessments must belong to the same group'}), 400
            parent_id = parent_ids.pop()

        # Create new group under determined parent
        target_group = Group(name=name, parent_ID=parent_id)
        db.session.add(target_group)
        db.session.flush()  # Get ID before using

    # Reassign children
    for g in groups:
        g.parent_ID = target_group.ID

    for a in assessments:
        a.group_ID = target_group.ID

    db.session.commit()

    return jsonify({
        'message': f"Items grouped under {'existing' if existing_group else 'new'} group.",
        'group_id': target_group.ID,
        'parent_id': target_group.parent_ID
    })

@app.route('/ungroup', methods=['POST'])
@token_required
def ungroup(current_admin):
    data = request.get_json()
    group_id = data.get('group_id')

    if not group_id:
        return jsonify({'error': 'Group ID is required'}), 400

    group = db.session.get(Group, group_id)
    if not group:
        return jsonify({'error': 'Group not found'}), 404

    parent_id = group.parent_ID  # can be None (top-level)
    reassigned_groups = []
    reassigned_assessments = []

    # Reassign all child groups to the parent group
    for child in group.children:
        child.parent_ID = parent_id
        reassigned_groups.append(child.ID)

    # Reassign all assessments of this group to the parent group
    assessments = Assessment.query.filter_by(group_ID=group.ID).all()
    for ass in assessments:
        ass.group_ID = parent_id
        reassigned_assessments.append(ass.ID)

    db.session.commit()  # Commit the reassignment changes before deleting

    # Delete the group itself
    db.session.delete(group)
    db.session.commit()

    return jsonify({
        'message': f"Group {group.name} successfully ungrouped.",
        'moved_to_parent': parent_id,
        'reassigned_groups': reassigned_groups,
        'reassigned_assessments': reassigned_assessments
    })

@app.route('/delete', methods=['DELETE'])
@token_required
def delete_items(current_admin):
    data = request.get_json()
    group_ids = data.get('groups', [])
    assessment_ids = data.get('assessments', [])
    dry_run = data.get('dry_run', False)  # Optional: skip deletion for testing

    deleted_files = []
    deleted_assessments = []
    deleted_groups = []

    # Delete assessments and their files
    for ass_id in assessment_ids:
        assessment = db.session.get(Assessment, ass_id)
        if assessment:
            filename = assessment.filename
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

            if not dry_run:
                # Delete the file if it exists
                if os.path.exists(file_path):
                    os.remove(file_path)
                    deleted_files.append(filename)

                # Get parent group before deletion
                group = assessment.group
                db.session.delete(assessment)
                db.session.commit()

                # Recursively delete empty ancestor groups
                check_and_delete_empty_ancestors(group)

            deleted_assessments.append(ass_id)

    # Delete provided groups and all their subgroups and assessments
    for group_id in group_ids:
        group = db.session.get(Group, group_id)
        if group:
            # Get all subgroups and assessments recursively
            all_subgroups = get_all_subgroups(group)
            all_assessments = get_all_assessments_in_group(group)
            
            # Delete all assessments in this group and its subgroups
            for assessment in all_assessments:
                filename = assessment.filename
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                
                if not dry_run:
                    # Delete the file if it exists
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        deleted_files.append(filename)
                    
                    db.session.delete(assessment)
                    deleted_assessments.append(assessment.ID)
            
            # Delete all subgroups
            for subgroup in all_subgroups:
                if not dry_run:
                    db.session.delete(subgroup)
                deleted_groups.append(subgroup.ID)
            
            # Delete the main group
            if not dry_run:
                db.session.delete(group)
                db.session.commit()
            deleted_groups.append(group.ID)

    return jsonify({
        "message": "Deletion completed.",
        "dry_run": dry_run,
        "deleted_files": deleted_files,
        "deleted_assessments": deleted_assessments,
        "deleted_groups": deleted_groups
    }), 200


@app.route('/admin/truncate')
def truncate_admin_table():
    try:
        # Delete all records from the Admin table
        Admin.query.delete()
        db.session.commit()
        return jsonify({'message': 'Admin table truncated successfully'}), 200
    except Exception as e:
        db.session.rollback()
        print(f"Error truncating admin table: {e}")
        return jsonify({'message': 'Error truncating admin table', 'error': str(e)}), 500




if __name__ == "__main__":
    threading.Thread(target=geocoding_worker, daemon=True).start()
    app.run(debug=True, host="0.0.0.0", port="5000")