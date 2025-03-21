from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy 
from flask_cors import CORS
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
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 30
}

db = SQLAlchemy(app)

class Assessment(db.Model):
    ID = db.Column(db.Integer, primary_key=True)
    start_lat = db.Column(db.Numeric(9,7), nullable=False)   # FIX: Use Numeric(9,7)
    start_lng = db.Column(db.Numeric(10,7), nullable=False)  # FIX: Use Numeric(10,7)
    end_lat = db.Column(db.Numeric(9,7), nullable=False)     # FIX: Use Numeric(9,7)
    end_lng = db.Column(db.Numeric(10,7), nullable=False)    # FIX: Use Numeric(10,7)
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
        start_lat = data.get("start_coor")[0]
        start_lng = data.get("start_coor")[1]
        end_lat = data.get("end_coor")[0]
        end_lng = data.get("end_coor")[1]
        date_created = data.get("date_created")
        cracks = data.get("cracks")

        # Validate required fields
        if not all([segment_id, start_lat, start_lng, end_lat, end_lng, date_created, cracks]):
            return jsonify({"response": "Missing required fields"}), 400

        # Save to the database
        new_assessment = Assessment(
            ID=segment_id,
            start_lat=start_lat,
            start_lng=start_lng,
            end_lat=end_lat,
            end_lng=end_lng,
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

@app.route('/ping', methods=['GET'])
def ping():

    cracks = Crack.query.all()
    result = [crack.to_dict() for crack in cracks]
    return jsonify(result), 200


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port="5000")

