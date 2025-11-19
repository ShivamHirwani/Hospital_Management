from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

# Initialize SQLAlchemy instance
db = SQLAlchemy()

# --- Core User Model ---
class User(UserMixin, db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(10), nullable=False)  # Admin, Doctor, Patient
    name = db.Column(db.String(100), nullable=False)
    contact_info = db.Column(db.String(100))
    is_active = db.Column(db.Boolean, default=True) # Used for blacklist/deactivation

    # Relationship to Doctor/Patient tables (One-to-One)
    doctor_profile = db.relationship('Doctor', backref='user', uselist=False)
    patient_profile = db.relationship('Patient', backref='user', uselist=False)

# --- Doctor & Specialization Models ---
class Specialization(db.Model):
    __tablename__ = 'specialization'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.String(255))
    
    doctors = db.relationship('Doctor', backref='specialization', lazy='dynamic')

class Doctor(db.Model):
    __tablename__ = 'doctor'
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    specialization_id = db.Column(db.Integer, db.ForeignKey('specialization.id'), nullable=False)
    
    # Appointments assigned to this doctor
    appointments = db.relationship('Appointment', backref='doctor', lazy='dynamic')

class Patient(db.Model):
    __tablename__ = 'patient'
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    date_of_birth = db.Column(db.String(10))
    
    # Appointments booked by this patient
    appointments = db.relationship('Appointment', backref='patient', lazy='dynamic')

# --- Appointment & Treatment Models ---
class Appointment(db.Model):
    __tablename__ = 'appointment'
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.user_id'), nullable=False)
    doctor_id = db.Column(db.Integer, db.ForeignKey('doctor.user_id'), nullable=False)
    date = db.Column(db.String(10), nullable=False)
    time = db.Column(db.String(5), nullable=False)
    status = db.Column(db.String(20), default='Booked') # Booked, Completed, Cancelled

    # Unique constraint to prevent double booking for one doctor
    __table_args__ = (db.UniqueConstraint('doctor_id', 'date', 'time', name='_doctor_time_uc'),)
    
    treatment_record = db.relationship('Treatment', backref='appointment', uselist=False)

class Treatment(db.Model):
    __tablename__ = 'treatment'
    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey('appointment.id'), unique=True, nullable=False)
    diagnosis = db.Column(db.Text)
    prescription = db.Column(db.Text)
    notes = db.Column(db.Text)

class DoctorAvailability(db.Model):
    __tablename__ = 'doctor_availability'
    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey('doctor.user_id'), nullable=False)
    date = db.Column(db.String(10), nullable=False)
    start_time = db.Column(db.String(5), nullable=False)
    end_time = db.Column(db.String(5), nullable=False)
    
    __table_args__ = (db.UniqueConstraint('doctor_id', 'date', 'start_time', name='_doctor_date_time_uc'),)

class MedicalRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    
    # Link to the specific appointment and the doctor/patient
    appointment_id = db.Column(db.Integer, db.ForeignKey('appointment.id'), unique=True, nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.user_id'), nullable=False)
    doctor_id = db.Column(db.Integer, db.ForeignKey('doctor.user_id'), nullable=False)
    
    # Consultation details
    diagnosis = db.Column(db.Text, nullable=False)
    notes = db.Column(db.Text, nullable=True) # Treatment notes, prescriptions, etc.
    consultation_date = db.Column(db.String(10), nullable=False) # Store the date string
    
    # Relationships
    appointment = db.relationship('Appointment', backref=db.backref('record', uselist=False))
    patient = db.relationship('Patient', backref='medical_records')
    doctor = db.relationship('Doctor', backref='consultations_given')

    def __repr__(self):
        return f'<MedicalRecord {self.id} | Appt {self.appointment_id}>'
