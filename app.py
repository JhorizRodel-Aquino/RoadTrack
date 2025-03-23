from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy 
from flask_cors import CORS
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime
import requests
import time
import threading
from threading import Event

app = Flask(__name__)

CORS(app)

geocode_event = Event()

# MySQL Database Configuration
hostname = 'localhost'
username = 'root'
password = ''
dbname = 'roadtrackdb'
# hostname = 'srv1668.hstgr.io'
# username = 'u854837124_roadtrack'
# password = 'RoadTrack123!'
# dbname = 'u854837124_roadtrackdb'

app.config['SQLALCHEMY_DATABASE_URI'] = f'mysql+pymysql://{username}:{password}@{hostname}/{dbname}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 30
}

db = SQLAlchemy(app)

class Group(db.Model):
    ID = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    mutable = db.Column(db.Boolean, default=True)
    parent_ID = db.Column(db.Integer, db.ForeignKey('group.ID'))
    assessments = db.relationship('Assessment', backref='group', lazy=True)
    children = db.relationship('Group', backref=db.backref('parent', remote_side=[ID]), lazy=True)

    def get_all_assessments(self):
        """
        Recursively fetch all assessments for this group and its child groups.
        """
        all_assessments = list(self.assessments)  # Start with assessments in this group

        for child in self.children:
            all_assessments.extend(child.get_all_assessments())

        return all_assessments
    
    def to_dict(self):
        return {
            'id': self.ID,
            'name': self.name,
            'parent_id': self.parent_ID,
        }

    def info_to_dict(self):
        return {
            'n_assess': len(self.get_all_assessments()),
            'n_cracks': self.total_cracks(),
            'date': self.latest_assessment_date()
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

class Crack(db.Model):
    ID = db.Column(db.Integer, primary_key=True)
    crack_type = db.Column(db.String(15), nullable=False)
    crack_severity = db.Column(db.String(10), nullable=False)
    assessment_ID = db.Column(db.Integer(), db.ForeignKey('assessment.ID'))

    def __repr__(self):
        return f'Crack {self.ID} under Assessment {self.assessment_ID}'

    def to_dict(self):
        return {
            'id': self.ID,
            'crack_type': self.crack_type,
            'crack_severity': self.crack_severity,
            'assessment_id': self.assessment_ID
        }

class Admin(db.Model):
    ID = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(50), nullable=False, unique=True)
    password_hash = db.Column(db.String(60), nullable=False)

    def __repr__(self):
        return f'Admin {self.email}'


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


# Create database tables
with app.app_context():
    db.create_all()


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
            segment_id = assessment.get("segment_id")
            start_lat = assessment.get("start_coor")[0]
            start_lon = assessment.get("start_coor")[1]
            end_lat = assessment.get("end_coor")[0]
            end_lon = assessment.get("end_coor")[1]
            date_created = assessment.get("date_created")
            cracks = assessment.get("cracks")

            # Validate required fields
            if not all([segment_id, start_lat, start_lon, end_lat, end_lon, date_created, cracks]):
                return jsonify({"response": "Missing required fields"}), 400

            # Save to the database
            new_assessment = Assessment(
                ID=segment_id,
                start_lat=start_lat,
                start_lon=start_lon,
                end_lat=end_lat,
                end_lon=end_lon,
                date=datetime.strptime(date_created, "%Y%m%d_%H-%M-%S")
            )
            db.session.add(new_assessment)
            db.session.flush()  # Get `ID` before committing

            for crack in cracks:
                new_crack = Crack(
                    assessment_ID=new_assessment.ID,
                    crack_type=crack["type"],
                    crack_severity=crack["severity"]  # Fix: Corrected spelling
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

# @app.route('/retry_geocoding')
# def retry_failed_geocoding():
#     failed_assessments = Assessment.query.filter_by(needs_geocoding=True).all()
#     retried = 0
#     for assessment in failed_assessments:
#         try:
#             reverse_geocode(assessment)
#             retried += 1
#         except Exception as e:
#             print(f"Still failed for {assessment} | {e}")
#     db.session.commit()
#     return f"Retry complete. Successfully updated {retried}/{len(failed_assessments)} assessments."

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
def get_group(ID):

    group = db.session.get(Group, ID)
    
    if not group:
        return jsonify({"error": f"Group with the id {ID} is not found"}), 404

    return jsonify(group.info_to_dict()), 200

@app.route('/group/<int:ID>/children', methods=['GET'])
def get_group_children(ID):
    group = db.session.get(Group, ID)
    
    if not group:
        return jsonify({"error": f"Group with ID {ID} not found."}), 404

    return jsonify(group.children_to_dict()), 200

@app.route('/group/<int:ID>/descendants', methods=['GET'])
def get_group_descendants(ID):
    group = db.session.get(Group, ID)
    
    if not group:
        return jsonify({"error": f"Group with ID {ID} not found."}), 404

    return jsonify(group.descendants_to_dict()), 200

@app.route('/group/<int:ID>/ancestors', methods=['GET'])
def get_group_ancestors(ID):
    group = db.session.get(Group, ID)
    
    if not group:
        return jsonify({"error": f"Group with ID {ID} not found."}), 404

    return jsonify(group.ancestors_to_dict()), 200

@app.route('/group/<int:ID>/summary', methods=['GET'])
def get_group_summary(ID):
    group = db.session.get(Group, ID)

    if not group:
        return jsonify({"error": f"Group with ID {ID} not found."}), 404

    return jsonify(group.summary_to_dict()), 200

@app.route('/group/<int:ID>/assessments', methods=['GET'])
def get_group_assessments(ID):
    group = db.session.get(Group, ID)
    
    if not group:
        return jsonify({"error": f"Group with ID {ID} not found."}), 404

    return jsonify(group.assessments_to_dict()), 200

@app.route('/assessment/<int:ID>/cracks', methods=['GET'])
def get_assessment(ID):
    assessment = db.session.get(Assessment, ID)

    if not assessment:
        return jsonify({"error": f"Group with ID {ID} not found."}), 404

    return jsonify(assessment.cracks_to_dict())



# @app.route('/group', methods=['GET'])
# def provinces():
#     if request.content_type != 'application/json':
#         return jsonify({"response": "Invalid Content-Type. Expected application/json"}), 400

#     provinces = Group.query.filter_by(parent_ID=None).all()
#     query = [province.to_dict() for province in provinces]
    
#     return jsonify(query), 200


if __name__ == "__main__":
    threading.Thread(target=geocoding_worker, daemon=True).start()
    app.run(debug=True, host="0.0.0.0", port="5000")
    

