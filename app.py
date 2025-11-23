import os
import functools
from datetime import datetime, timedelta
from sqlalchemy import or_, and_
from flask import Flask, render_template, redirect, url_for, request, flash, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

# --- APP SETUP ---
app = Flask(__name__)
# The database file must be created in the instance folder
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///hms.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.urandom(24) # Use a strong, secret key

# Initialize db and LoginManager *before* importing models
# (This is the critical fix for the circular dependency issue)
from models import db # Import the db object ONLY at the top
db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- MODEL IMPORTS (FIXED POSITION) ---
# Import all other models only after the db object is fully initialized with the app
from models import User, Doctor, Specialization, Appointment, Treatment, Patient, DoctorAvailability, MedicalRecord

# --- HELPER FUNCTIONS ---

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def role_required(role):
    """Decorator to restrict access based on user role."""
    def wrapper(func):
        @login_required
        @functools.wraps(func)
        def decorated_view(*args, **kwargs):
            if current_user.role != role:
                flash('Access denied. You do not have the required permissions.', 'danger')
                return redirect(url_for('dashboard'))
            return func(*args, **kwargs)
        return decorated_view
    return wrapper

def generate_slots(start_time_str, end_time_str, interval_minutes=30):
    """Generates a list of time strings (e.g., ['09:00', '09:30'])"""
    FMT = '%H:%M'
    # Use today's date arbitrarily for time arithmetic
    start_time = datetime.strptime(start_time_str, FMT)
    end_time = datetime.strptime(end_time_str, FMT)
    
    slots = []
    current_time = start_time
    while current_time < end_time:
        slots.append(current_time.strftime(FMT))
        current_time += timedelta(minutes=interval_minutes)
    return slots

def init_db_command():
    """Initializes the database and inserts the pre-existing admin."""
    with app.app_context():
        # Create all tables programmatically (MANDATORY REQUIREMENT)
        db.create_all()
        print("Database tables created.")

        # Insert pre-existing Admin (MANDATORY REQUIREMENT)
        if not User.query.filter_by(username='admin').first():
            hashed_password = generate_password_hash('adminpass', method='pbkdf2:sha256')
            admin = User(
                username='admin', 
                password_hash=hashed_password, 
                role='Admin', 
                name='Hospital Superuser'
            )
            db.session.add(admin)
            db.session.commit()
            print("Pre-existing Admin created (username: admin, password: adminpass)")

        # Optional: Add initial specializations
        if not Specialization.query.all():
            specializations = ['Cardiology', 'Pediatrics', 'Neurology', 'Oncology']
            for spec_name in specializations:
                db.session.add(Specialization(name=spec_name, description=f'Department of {spec_name}'))
            db.session.commit()
            print("Initial specializations added.")

# --- AUTHENTICATION ROUTES ---

@app.route('/', methods=['GET', 'POST'])
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password) and user.is_active:
            login_user(user)
            flash(f'Logged in successfully as {user.role}.', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Login failed. Check your username and password.', 'danger')
            
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# --- MAIN DASHBOARD ROUTING ---

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'Admin':
        return redirect(url_for('admin_dashboard'))
    elif current_user.role == 'Doctor':
        return redirect(url_for('doctor_dashboard'))
    elif current_user.role == 'Patient':
        return redirect(url_for('patient_dashboard'))
    else:
        # Should not happen
        return redirect(url_for('logout'))

# --- ROLE SPECIFIC DASHBOARDS ---

@app.route('/admin')
@role_required('Admin')
def admin_dashboard():
    # Admin dashboard must display total number of doctors, patients, and appointments.
    total_doctors = Doctor.query.count()
    total_patients = Patient.query.count()
    total_appointments = Appointment.query.count()
    
    upcoming_appointments = Appointment.query.filter(Appointment.status == 'Booked').order_by(Appointment.date, Appointment.time).limit(5).all()

    # NOTE: You'll need to create admin_dashboard.html
    context = {
        'total_doctors': total_doctors,
        'total_patients': total_patients,
        'total_appointments': total_appointments,
        'upcoming_appointments': upcoming_appointments
    }
    return render_template('admin_dashboard.html', **context)

# --- ADMIN APPOINTMENT MANAGEMENT (Cancel/Update) ---

@app.route('/admin/cancel_appointment/<int:appt_id>', methods=['POST'])
@role_required('Admin')
def admin_cancel_appointment(appt_id):
    appointment = Appointment.query.get_or_404(appt_id)
    
    if appointment.status == 'Booked':
        appointment.status = 'Cancelled'
        try:
            db.session.commit()
            flash(f'Appointment ID {appt_id} successfully cancelled.', 'success')
        except:
            db.session.rollback()
            flash('Failed to cancel appointment.', 'danger')
    else:
        flash(f'Appointment ID {appt_id} cannot be cancelled as status is {appointment.status}.', 'warning')
        
    return redirect(url_for('admin_dashboard'))

@app.route('/doctor')
@role_required('Doctor')
def doctor_dashboard():
    # Doctor’s dashboard must display upcoming appointments for the day/week.
    today = datetime.now().strftime('%Y-%m-%d')
    end_of_week = (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')
    
    # Appointments for the next 7 days (Booked or any status that isn't Cancelled)
    upcoming_appointments = Appointment.query.filter(
        Appointment.doctor_id == current_user.id,
        Appointment.date >= today,
        Appointment.date <= end_of_week,
        Appointment.status != 'Cancelled'
    ).order_by(Appointment.date, Appointment.time).all()

    # NOTE: You'll need to create doctor_dashboard.html
    return render_template('doctor_dashboard.html', appointments=upcoming_appointments)

@app.route('/patient')
@role_required('Patient')
def patient_dashboard():
    # 1. Fetch Specializations
    specializations = Specialization.query.all()
    
    # 2. Define today's date and current time for precise filtering
    today_date_str = datetime.now().strftime('%Y-%m-%d')
    current_time_str = datetime.now().strftime('%H:%M')
    
    # 3. Fetch Upcoming Appointments
    upcoming_appointments = Appointment.query.filter(
        Appointment.patient_id == current_user.id,
        
        # Include all active statuses
        Appointment.status.in_(['Booked', 'Rescheduled', 'Pending']),
        
        # CRITICAL FIX: Ensure the appointment is in the future
        or_(
            # Option A: Appointments on future days
            Appointment.date > today_date_str,
            # Option B: Appointments on today's date, but time hasn't passed yet
            and_(
                Appointment.date == today_date_str,
                Appointment.time >= current_time_str
            )
        )
    ).order_by(Appointment.date.asc(), Appointment.time.asc()).all()
    
    # 4. Render Template
    return render_template('patient_dashboard.html', 
                            specializations=specializations, 
                            upcoming_appointments=upcoming_appointments)
# --- Example CRUD for Admin (Add Doctor) ---

@app.route('/admin/add_doctor', methods=['GET', 'POST'])
@role_required('Admin')
def add_doctor():
    specializations = Specialization.query.all()
    
    if request.method == 'POST':
        name = request.form.get('name')
        username = request.form.get('username')
        password = request.form.get('password')
        specialization_id = request.form.get('specialization_id')
        contact_info = request.form.get('contact_info')

        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return redirect(url_for('add_doctor'))

        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        
        try:
            # 1. Create User entry
            new_user = User(
                username=username,
                password_hash=hashed_password,
                role='Doctor',
                name=name,
                contact_info=contact_info
            )
            db.session.add(new_user)
            db.session.flush() # Get the user.id before commit
            
            # 2. Create Doctor profile entry
            new_doctor = Doctor(
                user_id=new_user.id,
                specialization_id=specialization_id
            )
            db.session.add(new_doctor)
            db.session.commit()
            flash(f'Doctor {name} added successfully.', 'success')
            return redirect(url_for('admin_dashboard'))
        except Exception as e:
            db.session.rollback()
            flash(f'An error occurred: {e}', 'danger')

    # NOTE: You'll need to create add_doctor.html
    return render_template('add_doctor.html', specializations=specializations)

# --- ADMIN DOCTOR MANAGEMENT (CRUD) ---

@app.route('/admin/doctors')
@role_required('Admin')
def manage_doctors():
    # READ: View all doctors
    doctors = Doctor.query.join(User).all()
    # NOTE: You'll need to create manage_doctors.html
    return render_template('manage_doctors.html', doctors=doctors)

@app.route('/admin/edit_doctor/<int:user_id>', methods=['GET', 'POST'])
@role_required('Admin')
def edit_doctor(user_id):
    # UPDATE: Edit doctor profile
    user = User.query.get_or_404(user_id)
    if user.role != 'Doctor':
        flash('User is not a doctor.', 'danger')
        return redirect(url_for('manage_doctors'))
    
    doctor = Doctor.query.get_or_404(user_id)
    specializations = Specialization.query.all()
    
    if request.method == 'POST':
        user.name = request.form.get('name')
        user.contact_info = request.form.get('contact_info')
        doctor.specialization_id = request.form.get('specialization_id')
        
        try:
            db.session.commit()
            flash(f'Doctor {user.name} updated successfully.', 'success')
            return redirect(url_for('manage_doctors'))
        except Exception as e:
            db.session.rollback()
            flash(f'Failed to update doctor: {e}', 'danger')
            
    # NOTE: You'll need to create edit_doctor.html
    return render_template('edit_doctor.html', user=user, doctor=doctor, specializations=specializations)

@app.route('/admin/toggle_blacklist/<int:user_id>', methods=['POST'])
@role_required('Admin')
def toggle_blacklist(user_id):
    # DELETE/BLACKLIST: Set user status to inactive
    user = User.query.get_or_404(user_id)
    
    if user.role == 'Admin':
        flash('Cannot blacklist the admin user.', 'danger')
        return redirect(url_for('manage_doctors'))

    # Toggle the active status
    user.is_active = not user.is_active
    
    try:
        db.session.commit()
        status = "Blacklisted (Inactive)" if not user.is_active else "Activated (Active)"
        flash(f'User {user.name} status updated to {status}.', 'success')
    except:
        db.session.rollback()
        flash('Failed to update user status.', 'danger')

    return redirect(url_for('manage_doctors'))

# --- CORE FUNCTIONALITY EXAMPLE: PATIENT REGISTRATION ---

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        name = request.form.get('name')
        username = request.form.get('username')
        password = request.form.get('password')
        dob = request.form.get('date_of_birth')

        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return redirect(url_for('register'))

        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        
        try:
            # 1. Create User entry
            new_user = User(
                username=username,
                password_hash=hashed_password,
                role='Patient',
                name=name
            )
            db.session.add(new_user)
            db.session.flush()
            
            # 2. Create Patient profile entry
            new_patient = Patient(
                user_id=new_user.id,
                date_of_birth=dob
            )
            db.session.add(new_patient)
            db.session.commit()
            
            login_user(new_user)
            flash('Registration successful! You are now logged in.', 'success')
            return redirect(url_for('patient_dashboard'))
        except Exception as e:
            db.session.rollback()
            flash(f'Registration failed: {e}', 'danger')

    # NOTE: You'll need to create register.html
    return render_template('register.html')

# --- DOCTOR VIEW TREATMENT NOTES ROUTE ---

@app.route('/doctor/view_notes/<int:appt_id>', methods=['GET'])
@role_required('Doctor')
def doctor_view_treatment(appt_id):
    appointment = Appointment.query.get_or_404(appt_id)
    
    # Security Check: Ensure the appointment belongs to the logged-in doctor
    if appointment.doctor_id != current_user.id:
        flash('Access denied. This is not your patient record.', 'danger')
        return redirect(url_for('doctor_dashboard'))

    medical_record = MedicalRecord.query.filter_by(appointment_id=appt_id).first()
    
    if not medical_record:
        flash('No consultation record found for this appointment.', 'danger')
        return redirect(url_for('doctor_dashboard'))
    
    return render_template('view_treatment_notes.html', 
                            appointment=appointment, 
                            medical_record=medical_record)
# --- PATIENT APPOINTMENT ROUTES ---

@app.route('/patient/find_doctors', methods=['GET'])
@role_required('Patient')
def find_doctors():
    specialization_id = request.args.get('specialization_id')
    
    # Get dates for the next 7 days
    start_date = datetime.now().strftime('%Y-%m-%d')
    end_date = (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')
    date_list = [(datetime.now() + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(7)]

    # 1. Fetch Doctors
    if specialization_id:
        doctors = Doctor.query.filter_by(specialization_id=specialization_id).all()
    else:
        doctors = Doctor.query.all()
        
    doctor_ids = [d.user_id for d in doctors]
    
    # If no doctors are found, return early with an empty result to avoid DB errors
    if not doctor_ids:
        return render_template('book_appointment.html', 
                                doctors=[], 
                                date_list=date_list, 
                                bookable_slots_map={},
                                current_spec_id=specialization_id,
                                datetime=datetime)

    # 2. Fetch all current set availability records for these doctors
    availability_records = DoctorAvailability.query.filter(
        DoctorAvailability.doctor_id.in_(doctor_ids),
        DoctorAvailability.date.between(start_date, end_date)
    ).all()
    
    # 3. Fetch all currently Booked/Completed appointments
    booked_appointments = Appointment.query.filter(
        Appointment.doctor_id.in_(doctor_ids),
        Appointment.date.between(start_date, end_date),
        # Check both Booked and Completed to prevent booking slots that have passed/been used
        Appointment.status.in_(['Booked', 'Completed']) 
    ).all()
    
    # Map currently booked slots for quick lookup: (doctor_id, date, time)
    booked_slots_set = set()
    for appt in booked_appointments:
        booked_slots_set.add((appt.doctor_id, appt.date, appt.time))

    # 4. Generate the final list of bookable slots
    availability_map = {} # Map raw set availability
    for record in availability_records:
        if record.doctor_id not in availability_map:
            availability_map[record.doctor_id] = {}
        availability_map[record.doctor_id][record.date] = record
        
    bookable_slots_map = {}
    for doctor in doctors:
        bookable_slots_map[doctor.user_id] = {}
        
        for date_str in date_list:
            record = availability_map.get(doctor.user_id, {}).get(date_str)
            
            if record:
                # Generate all potential 30-minute slots using the helper function
                all_day_slots = generate_slots(record.start_time, record.end_time)
                
                # Filter out slots that are already booked
                available_slots = [
                    slot for slot in all_day_slots
                    if (doctor.user_id, date_str, slot) not in booked_slots_set
                ]
                bookable_slots_map[doctor.user_id][date_str] = available_slots
            else:
                bookable_slots_map[doctor.user_id][date_str] = [] # Doctor is not available

    # 5. Render Template with new map
    return render_template('book_appointment.html', 
                            doctors=doctors, 
                            date_list=date_list, 
                            bookable_slots_map=bookable_slots_map, # <<< CRITICAL VARIABLE
                            current_spec_id=specialization_id,
                            datetime=datetime)

@app.route('/patient/book', methods=['POST'])
@role_required('Patient')
def book_appointment():
    doctor_id = request.form.get('doctor_id')
    date = request.form.get('date')
    time = request.form.get('time')
    patient_id = current_user.id
    
    # 1. Input Validation
    if not all([doctor_id, date, time]):
        flash('Missing appointment details.', 'danger')
        return redirect(url_for('patient_dashboard'))

    # 2. Prevent Multiple Appointments at the Same Date and Time for the same Doctor (MANDATORY)
    conflict = Appointment.query.filter(
        Appointment.doctor_id == doctor_id,
        Appointment.date == date,
        Appointment.time == time,
        Appointment.status == 'Booked'
    ).first()

    if conflict:
        flash('This exact time slot is already booked for the doctor. Please select another.', 'danger')
        return redirect(url_for('find_doctors', specialization_id=request.form.get('specialization_id'))) # Redirect back to the search results
        
    try:
        new_appointment = Appointment(
            patient_id=patient_id,
            doctor_id=doctor_id,
            date=date,
            time=time,
            status='Booked'
        )
        db.session.add(new_appointment)
        db.session.commit()
        flash('Appointment booked successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error booking appointment: {e}', 'danger')

    return redirect(url_for('patient_dashboard'))

# --- PATIENT CANCEL APPOINTMENT (UPDATE STATUS) ---

@app.route('/patient/cancel_appointment/<int:appt_id>', methods=['POST'])
@role_required('Patient')
def patient_cancel_appointment(appt_id):
    appointment = Appointment.query.get_or_404(appt_id)
    
    # Security Check: Ensure patient owns this appointment
    if appointment.patient_id != current_user.id:
        flash('Access denied. This is not your appointment.', 'danger')
        return redirect(url_for('patient_dashboard'))

    if appointment.status in ['Booked', 'Rescheduled']:
        appointment.status = 'Cancelled'
        try:
            db.session.commit()
            flash(f'Appointment ID {appt_id} successfully cancelled.', 'success')
        except:
            db.session.rollback()
            flash('Failed to cancel appointment.', 'danger')
    else:
        flash(f'Appointment ID {appt_id} cannot be cancelled as status is {appointment.status}.', 'warning')
        
    return redirect(url_for('patient_dashboard'))

# --- PATIENT PROFILE EDIT ROUTE ---

@app.route('/patient/edit_profile', methods=['GET', 'POST'])
@login_required
@role_required('Patient')
def patient_edit_profile():
    # Get the User object (already available as current_user)
    user = current_user
    # Get the corresponding Patient object
    patient = Patient.query.filter_by(user_id=user.id).first()
    
    if not patient:
        flash('Patient profile data not found.', 'danger')
        return redirect(url_for('patient_dashboard'))

    if request.method == 'POST':
        # 1. Update User Details (Name, Contact Info)
        user.name = request.form.get('name')
        user.contact_info = request.form.get('contact_info')
        
        # 2. Update Patient Details (Date of Birth)
        patient.date_of_birth = request.form.get('date_of_birth')

        try:
            db.session.commit()
            flash('Your profile has been successfully updated.', 'success')
            return redirect(url_for('patient_dashboard'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating profile: {e}', 'danger')
            return redirect(url_for('patient_edit_profile'))

    # If GET, display the form
    return render_template('patient_edit_profile.html', user=user, patient=patient)

# --- DOCTOR TREATMENT ENTRY ROUTES (CRUD for Treatment) ---

@app.route('/doctor/complete_appointment/<int:appt_id>', methods=['GET', 'POST'])
@role_required('Doctor')
def complete_appointment(appt_id):
    appointment = Appointment.query.get_or_404(appt_id)
    
    # Security Check: Ensure the doctor is handling their assigned appointment
    if appointment.doctor_id != current_user.id:
        abort(403) 
        
    if request.method == 'POST':
        diagnosis = request.form.get('diagnosis')
        prescription = request.form.get('prescription')
        notes = request.form.get('notes')
        
        try:
            # 1. Update Appointment Status
            appointment.status = 'Completed'
            
            # 2. Create Treatment Record
            treatment = Treatment(
                appointment_id=appointment.id,
                diagnosis=diagnosis,
                prescription=prescription,
                notes=notes
            )
            db.session.add(treatment)
            db.session.commit()
            
            flash('Consultation completed and treatment notes saved.', 'success')
            return redirect(url_for('doctor_dashboard'))
        except Exception as e:
            db.session.rollback()
            flash(f'Failed to save treatment details: {e}', 'danger')
            return redirect(url_for('doctor_dashboard'))

    # GET request: Show consultation form
    # NOTE: You'll need to create consultation_form.html
    return render_template('consultation_form.html', appointment=appointment)

# --- DOCTOR CONSULTATION ROUTES ---

@app.route('/doctor/consultation/<int:appt_id>', methods=['GET', 'POST'])
@role_required('Doctor')
def start_consultation(appt_id):
    appointment = Appointment.query.get_or_404(appt_id)
    
    # Security Check: Ensure the appointment belongs to the logged-in doctor
    if appointment.doctor_id != current_user.id:
        flash('Access denied. This appointment is not assigned to you.', 'danger')
        return redirect(url_for('doctor_dashboard'))

    # Check status: Only allow consultation for active or rescheduled appointments
    if appointment.status not in ['Booked', 'Rescheduled', 'Pending']:
        flash(f'Cannot start consultation. Appointment status is {appointment.status}.', 'warning')
        return redirect(url_for('doctor_dashboard'))

    # If GET, display the consultation form
    if request.method == 'GET':
        patient = appointment.patient
        return render_template('start_consultation.html', 
                                appointment=appointment, 
                                patient=patient)

    # If POST, process the consultation data
    elif request.method == 'POST':
        diagnosis = request.form.get('diagnosis')
        notes = request.form.get('notes')
        
        # 1. Update Appointment Status
        appointment.status = 'Completed' 
        
        # 2. CREATE NEW MEDICAL RECORD
        new_record = MedicalRecord(
            appointment_id=appointment.id,
            patient_id=appointment.patient_id,
            doctor_id=current_user.id,
            diagnosis=diagnosis,
            notes=notes,
            consultation_date=appointment.date
        )
        
        db.session.add(new_record)

        try:
            db.session.commit()
            flash(f'Consultation for patient {appointment.patient.user.name} completed and status updated.', 'success')
            return redirect(url_for('doctor_dashboard'))
        except Exception as e:
            db.session.rollback()
            flash(f'Failed to save consultation details: {e}', 'danger')
            return redirect(url_for('start_consultation', appt_id=appt_id))

# --- PATIENT HISTORY ROUTE ---

@app.route('/patient/history')
@role_required('Patient')
def patient_history():
    # Show past appointment history with diagnosis and prescriptions.
    history = Appointment.query.filter(
        Appointment.patient_id == current_user.id,
        Appointment.status == 'Completed'
    ).order_by(Appointment.date.desc(), Appointment.time.desc()).all()
    
    # NOTE: We need a dedicated template: patient_history.html
    return render_template('patient_history.html', history=history)

# --- DOCTOR AVAILABILITY (Quick Fix to fulfill a requirement) ---

@app.route('/doctor/set_availability', methods=['GET', 'POST'])
@role_required('Doctor')
def set_doctor_availability():
    # This is a simplified route to allow doctors to set their 7-day schedule
    if request.method == 'POST':
        date = request.form.get('date')
        start_time = request.form.get('start_time')
        end_time = request.form.get('end_time')
        
        if not all([date, start_time, end_time]):
            flash('All fields are required.', 'danger')
            return redirect(url_for('set_doctor_availability'))
            
        try:
            # Check for existing record and update/insert
            availability = DoctorAvailability.query.filter_by(doctor_id=current_user.id, date=date).first()
            if availability:
                availability.start_time = start_time
                availability.end_time = end_time
                flash(f'Availability for {date} updated.', 'success')
            else:
                new_availability = DoctorAvailability(
                    doctor_id=current_user.id,
                    date=date,
                    start_time=start_time,
                    end_time=end_time
                )
                db.session.add(new_availability)
                flash(f'Availability for {date} set.', 'success')
                
            db.session.commit()
            return redirect(url_for('doctor_dashboard'))
        except Exception as e:
            db.session.rollback()
            # This catch handles the unique constraint if the doctor tries to add the same date twice
            flash('Error setting availability. Check your time slot or if you already set it for this day.', 'danger')
    
    # Pre-populate dates for the next 7 days
    date_list = [(datetime.now() + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(1, 8)]
    
    # NOTE: You'll need to create set_availability.html
    return render_template('set_availability.html', date_list=date_list, datetime=datetime)

# --- DOCTOR VIEW PATIENT HISTORY ROUTE ---

@app.route('/doctor/patient_history/<int:patient_id>')
@role_required('Doctor')
def doctor_view_patient_history(patient_id):
    # Fetch patient's details
    patient_user = User.query.get_or_404(patient_id)
    if patient_user.role != 'Patient':
        abort(404) 
        
    # Fetch all completed appointments for this patient
    history = Appointment.query.filter(
        Appointment.patient_id == patient_id,
        Appointment.status == 'Completed'
    ).order_by(Appointment.date.desc(), Appointment.time.desc()).all()

    # NOTE: We need a dedicated template: doctor_patient_history.html
    return render_template('doctor_patient_history.html', 
                            patient_name=patient_user.name, 
                            history=history)

# --- ADMIN PATIENT MANAGEMENT ROUTES (CRUD) ---

@app.route('/admin/patients')
@role_required('Admin')
def manage_patients():
    # READ: View all patients, including their active status
    patients = Patient.query.join(User).all()
    
    # NOTE: We need a dedicated template: manage_patients.html
    return render_template('manage_patients.html', patients=patients)

@app.route('/admin/edit_patient/<int:user_id>', methods=['GET', 'POST'])
@role_required('Admin')
def edit_patient(user_id):
    # UPDATE: Edit patient profile (User and Patient table data)
    user = User.query.get_or_404(user_id)
    if user.role != 'Patient':
        flash('User is not a patient.', 'danger')
        return redirect(url_for('manage_patients'))
    
    patient = Patient.query.get_or_404(user_id)
    
    if request.method == 'POST':
        # Update User fields (name, contact info)
        user.name = request.form.get('name')
        user.contact_info = request.form.get('contact_info')
        # Update Patient fields (date of birth)
        patient.date_of_birth = request.form.get('date_of_birth')
        
        try:
            db.session.commit()
            flash(f'Patient {user.name} updated successfully.', 'success')
            return redirect(url_for('manage_patients'))
        except Exception as e:
            db.session.rollback()
            flash(f'Failed to update patient: {e}', 'danger')
            
    # NOTE: We need a dedicated template: edit_patient.html
    return render_template('edit_patient.html', user=user, patient=patient)


# --- INITIAL SETUP RUNNER ---

if __name__ == '__main__':
    # Initialize the database and admin on the first run
    with app.app_context():
        # This will create tables and the initial admin if they don't exist
        init_db_command() 
    
    # Start the Flask development server
    app.run(debug=True)
