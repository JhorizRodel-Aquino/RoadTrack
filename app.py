from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy 
from geoalchemy2 import Geometry
from flask_cors import CORS
from shapely.geometry import Point
from geoalchemy2.shape import from_shape
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime

app = Flask(__name__)

CORS(app)

# MySQL Database Configuration
# hostname = 'localhost'
# username = 'root'
# password = ''
# dbname = 'roadtrackdb'
hostname = 'srv1668.hstgr.io'
username = 'u854837124_roadtrack'
password = 'RoadTrack123!'
dbname = 'u854837124_roadtrackdb'

app.config['SQLALCHEMY_DATABASE_URI'] = f'mysql+pymysql://{username}:{password}@{hostname}/{dbname}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class Assessment(db.Model):
    ID = db.Column(db.Integer, primary_key=True)
    start_coor = db.Column(Geometry('POINT'), nullable=False)
    end_coor = db.Column(Geometry('POINT'), nullable=False)
    date = db.Column(db.DateTime, nullable=False)
    cracks = db.relationship('Crack', backref='assessment_group', lazy=True)

    def __repr__(self):
        return f'Assessment {self.ID}'

class Crack(db.Model):
    ID = db.Column(db.Integer, primary_key=True)
    crack_type = db.Column(db.String(15), nullable=False)
    crack_severity = db.Column(db.String(10), nullable=False)
    assessment_ID = db.Column(db.Integer(), db.ForeignKey('assessment.ID'))

    def __repr__(self):
        return f'Crack {self.ID} under Assessment {self.assessment}'

class Admin(db.Model):
    ID = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(50), nullable=False, unique=True)
    password_hash = db.Column(db.String(60), nullable=False)

    def __repr__(self):
        return f'Admin {self.email}'

# Create database tables
with app.app_context():
    db.create_all()


@app.route('/')
def home():
    return "Hello World!"

@app.route('/update_logs', methods=['POST'])
def update_logs():
    if request.content_type != 'application/json':
        return jsonify({"response": "Invalid Content-Type. Expected application/json"}), 400

    try:
        data = request.get_json()

        # Extract required fields
        segment_id = data.get("segment_id")
        start_coor = data.get("start_coor")
        end_coor = data.get("end_coor")
        date_created = data.get("date_created")
        cracks = data.get("cracks")

        if isinstance(start_coor, list) and isinstance(end_coor, list):
            start_coor = from_shape(Point(start_coor[1], start_coor[0]))  # (lng, lat)
            end_coor = from_shape(Point(end_coor[1], end_coor[0]))  # (lng, lat)
        else:
            return jsonify({"response": "Invalid coordinate format"}), 400

        # Validate required fields
        if not all([segment_id, start_coor, end_coor, date_created, cracks]):
            return jsonify({"response": "Missing required fields"}), 400

        # Save to the database
        new_assessment = Assessment(
            ID=segment_id,
            start_coor=start_coor,
            end_coor=end_coor,
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
        return jsonify({"response": "Logs updated successfully!"}), 200

    except SQLAlchemyError as e:
        db.session.rollback()
        return jsonify({"response": f"Database error: {str(e)}"}), 500

    except Exception as e:
        return jsonify({"response": f"Something went wrong: {str(e)}"}), 500

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port="5000")

