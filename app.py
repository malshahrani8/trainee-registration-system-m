from flask import (Flask, render_template, request, redirect, url_for, 
                   flash, send_file, Response, jsonify, make_response)
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from models import db, Admin, Trainee, TestSession, CourseEnrollment, Grade, SPECIALIZATIONS, COURSES
from forms import (LoginForm, TraineeRegistrationForm, SessionForm, 
                   CourseEnrollmentUploadForm, GradeForm)
from email_service import mail, send_confirmation_email
from csv_export import generate_session_report_csv
from csv_importer import import_course_enrollments_from_csv
from config import Config
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timedelta
import os

app = Flask(__name__)
app.config.from_object(Config)

os.makedirs('uploads', exist_ok=True)

db.init_app(app)

try:
    from email_service import MAIL_AVAILABLE
    if MAIL_AVAILABLE and app.config.get('MAIL_USERNAME'):
        mail.init_app(app)
except Exception:
    pass

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'admin_login'
login_manager.login_message = 'الرجاء تسجيل الدخول'
login_manager.login_message_category = 'warning'

@login_manager.user_loader
def load_user(user_id):
    return Admin.query.get(int(user_id))


# ═══════════════════════════════════════════════════════
# دوال مساعدة
# ═══════════════════════════════════════════════════════

def init_db():
    with app.app_context():
        db.create_all()
        if not Admin.query.filter_by(username='admin').first():
            admin = Admin(
                username='admin',
                email='admin@system.com',
                full_name='مسؤول النظام'
            )
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print("✅ تم إنشاء حساب مسؤول (admin / admin123)")


def check_time_location_conflict(session_date, session_time, location, exclude_id=None):
    """
    ✅ فحص التعارض الزماني والمكاني للجلسات
    يُرجع (is_conflict, conflicting_session)
    """
    conflict = TestSession.query.filter(
        TestSession.session_date == session_date,
        TestSession.session_time == session_time,
        TestSession.location == location
    )
    
    if exclude_id:
        conflict = conflict.filter(TestSession.id != exclude_id)
    
    conflicting_session = conflict.first()
    
    if conflicting_session:
        return True, conflicting_session
    return False, None


def check_registration_rules(trainee_id, session_id, course_name):
    """
    ✅ سياسة الإعادة المحدثة (Retake Policy):
    - يُسمح بالإعادة إذا:
      * المتدرب راسب (درجة < 60)
      * أو كان غائباً في الجلسة السابقة
    - يُمنع التسجيل فقط إذا:
      * حضر الاختبار AND درجته >= 60
    """
    # 1. التحقق من التسجيل في المقرر
    enrollment = CourseEnrollment.query.filter_by(
        trainee_id=trainee_id, course_name=course_name
    ).first()
    
    if not enrollment:
        return False, 'عذراً، أنت غير مسجل في هذا المقرر'
    
    # 2. جلب جميع تسجيلات المتدرب لهذا المقرر
    trainee_registrations = Trainee.query.filter_by(trainee_id=trainee_id).join(TestSession).filter(
        TestSession.course_name == course_name
    ).all()
    
    if len(trainee_registrations) >= 3:
        return False, 'وصلت للحد الأقصى (3 جلسات) لهذا المقرر'
    
    # 3. التحقق من عدم التسجيل في نفس الجلسة
    for reg in trainee_registrations:
        if reg.session_id == int(session_id):
            return False, 'أنت مسجل بالفعل في هذه الجلسة'
    
    # 4. ✅ سياسة الإعادة المحدثة
    if len(trainee_registrations) > 0:
        sorted_regs = sorted(trainee_registrations, key=lambda x: x.registration_order)
        last_registration = sorted_regs[-1]
        
        # التحقق من حالة الجلسة الأخيرة
        if last_registration.attendance_status == 'attended':
            # حضر الاختبار - نتحقق من الدرجة
            if last_registration.passed:
                return False, f'🎉 لقد اجتزت الاختبار بنجاح (الدرجة: {last_registration.latest_grade.score}) ولا تحتاج لإعادة الاختبار'
            else:
                # حضر لكنه راسب - يُسمح بالإعادة
                pass
        elif last_registration.attendance_status == 'missed':
            # غائب - يُسمح بالإعادة
            pass
        else:
            # لم يحضر بعد - يجب الانتظار
            return False, 'لم تُرصد حالة حضورك في الجلسة السابقة بعد'
        
        # 5. التحقق من عدم التداخل الزمني
        new_session = TestSession.query.get(session_id)
        for reg in trainee_registrations:
            existing_session = reg.session
            if (existing_session.session_date == new_session.session_date and 
                existing_session.session_time == new_session.session_time):
                return False, 'لا يمكن التسجيل في جلسات متزامنة زمنياً'
    
    return True, 'التسجيل مسموح'


# ═══════════════════════════════════════════════════════
# المسارات العامة
# ═══════════════════════════════════════════════════════

@app.route('/')
def index():
    form = TraineeRegistrationForm()
    return render_template('index.html', form=form, specializations=SPECIALIZATIONS)


@app.route('/api/sessions')
def api_sessions():
    specialization = request.args.get('specialization')
    course_name = request.args.get('course_name', 'مقدمة تطبيقات الحاسب')
    
    if not specialization:
        return {'sessions': []}
    
    available_sessions = TestSession.query.filter_by(
        specialization=specialization, course_name=course_name
    ).order_by(TestSession.session_date, TestSession.session_time).all()
    
    available_sessions = [s for s in available_sessions if not s.is_full]
    
    sessions_data = []
    for session in available_sessions:
        sessions_data.append({
            'id': session.id,
            'course_name': session.course_name,
            'specialization': session.specialization,
            'session_date': session.session_date.strftime('%Y-%m-%d'),
            'session_time': session.session_time.strftime('%H:%M'),
            'location': session.location,
            'current_count': session.current_count,
            'max_capacity': session.max_capacity,
            'available_seats': session.available_seats
        })
    
    return {'sessions': sessions_data}


@app.route('/api/check-trainee')
def api_check_trainee():
    trainee_id = request.args.get('trainee_id', '').strip()
    course_name = request.args.get('course_name', 'مقدمة تطبيقات الحاسب')
    
    if not trainee_id or len(trainee_id) < 6:
        return {'found': False, 'message': 'أدخل الرقم التدريبي كاملاً'}
    
    enrollment = CourseEnrollment.query.filter_by(
        trainee_id=trainee_id, course_name=course_name
    ).first()
    
    if enrollment:
        return {
            'found': True,
            'message': 'تم العثور على المتدرب',
            'full_name': enrollment.full_name,
            'specialization': enrollment.specialization,
            'phone': enrollment.phone or '',
            'email': enrollment.email or ''
        }
    
    return {'found': False, 'message': 'الرقم التدريبي غير مسجل في هذا المقرر'}


@app.route('/api/check-session-conflict')
def api_check_session_conflict():
    """✅ API لفحص التعارض الزماني والمكاني"""
    session_date = request.args.get('session_date')
    session_time = request.args.get('session_time')
    location = request.args.get('location', '').strip()
    exclude_id = request.args.get('exclude_id')
    
    if not all([session_date, session_time, location]):
        return {'conflict': False, 'message': 'بيانات غير مكتملة'}
    
    try:
        date_obj = datetime.strptime(session_date, '%Y-%m-%d').date()
        time_obj = datetime.strptime(session_time, '%H:%M').time()
    except ValueError:
        return {'conflict': False, 'message': 'صيغة التاريخ أو الوقت غير صحيحة'}
    
    is_conflict, conflicting_session = check_time_location_conflict(
        date_obj, time_obj, location,
        exclude_id=int(exclude_id) if exclude_id else None
    )
    
    if is_conflict:
        return {
            'conflict': True,
            'message': f'⚠️ المعمل "{conflicting_session.location}" مخصص لجلسة أخرى في هذا الوقت ({conflicting_session.course_name} - {conflicting_session.specialization})'
        }
    
    return {'conflict': False, 'message': '✅ لا يوجد تعارض'}


@app.route('/register', methods=['POST'])
def register():
    form = TraineeRegistrationForm(request.form)
    
    if not form.validate_on_submit():
        for field, errors in form.errors.items():
            for error in errors:
                flash(error, 'danger')
        return redirect(url_for('index'))
    
    # ✅ التحقق من الإقرارين
    if not form.declaration.data:
        flash('يجب الموافقة على الإقرار والتعهد', 'danger')
        return redirect(url_for('index'))
    
    if not form.acknowledge_instructions.data:
        flash('يجب الإقرار بالاطلاع على تعليمات الاختبار', 'danger')
        return redirect(url_for('index'))
    
    try:
        trainee_id = form.trainee_id.data.strip()
        email = form.email.data.strip().lower() if form.email.data else None
        phone = form.phone.data.strip() if form.phone.data else None
        full_name = form.full_name.data.strip()
        specialization = form.specialization.data
        session_id = form.session_id.data
        
        session = TestSession.query.get(session_id)
        
        if not session or session.is_full:
            flash('الجلسة غير متاحة', 'danger')
            return redirect(url_for('index'))
        
        # ✅ التحقق من قواعد التسجيل (يشمل سياسة الإعادة)
        is_allowed, message = check_registration_rules(trainee_id, session_id, session.course_name)
        if not is_allowed:
            flash(message, 'danger')
            return redirect(url_for('index'))
        
        existing_count = Trainee.query.filter_by(trainee_id=trainee_id).join(TestSession).filter(
            TestSession.course_name == session.course_name
        ).count()
        registration_order = existing_count + 1
        
        session = db.session.query(TestSession).filter_by(id=session_id).with_for_update().first()
        
        if session.is_full:
            flash('اكتملت الجلسة', 'danger')
            return redirect(url_for('index'))
        
        new_trainee = Trainee(
            full_name=full_name,
            email=email,
            phone=phone,
            trainee_id=trainee_id,
            specialization=specialization,
            session_id=session_id,
            registration_order=registration_order,
            attendance_status='pending',
            acknowledged_instructions=True  # ✅ تم الإقرار
        )
        
        db.session.add(new_trainee)
        db.session.commit()
        
        email_sent, email_msg = send_confirmation_email(new_trainee, session)
        
        return render_template('success.html',
                             trainee=new_trainee,
                             session=session,
                             email_sent=email_sent)
        
    except IntegrityError:
        db.session.rollback()
        flash('الرقم التدريبي مسجل مسبقاً في هذه الجلسة', 'danger')
        return redirect(url_for('index'))
    except Exception as e:
        db.session.rollback()
        flash(f'خطأ: {str(e)}', 'danger')
        return redirect(url_for('index'))


# ═══════════════════════════════════════════════════════
# 🆕 مسار طباعة الإقرار
# ═══════════════════════════════════════════════════════

@app.route('/print-acknowledgment/<int:trainee_id>')
def print_acknowledgment(trainee_id):
    """طباعة إقرار المتدرب بتعليمات الاختبار"""
    trainee = Trainee.query.get_or_404(trainee_id)
    session = trainee.session
    
    html_content = f"""
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <title>إقرار المتدرب - {trainee.full_name}</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700;900&display=swap');
            body {{
                font-family: 'Tajawal', Arial, sans-serif;
                padding: 40px;
                direction: rtl;
                color: #1a1a1a;
                line-height: 1.8;
            }}
            .header {{
                text-align: center;
                border-bottom: 4px solid #2563eb;
                padding-bottom: 20px;
                margin-bottom: 30px;
            }}
            .header h1 {{
                color: #2563eb;
                margin: 10px 0;
                font-size: 28px;
            }}
            .header h2 {{
                color: #666;
                font-size: 18px;
                margin: 5px 0;
            }}
            .info-box {{
                background: #f0f9ff;
                border: 2px solid #2563eb;
                border-radius: 10px;
                padding: 20px;
                margin: 20px 0;
            }}
            .info-box h3 {{
                color: #2563eb;
                margin-top: 0;
            }}
            .info-row {{
                display: flex;
                justify-content: space-between;
                padding: 8px 0;
                border-bottom: 1px dashed #ccc;
            }}
            .info-row:last-child {{
                border-bottom: none;
            }}
            .acknowledgment-box {{
                background: #fef3c7;
                border: 2px solid #f59e0b;
                border-radius: 10px;
                padding: 25px;
                margin: 30px 0;
            }}
            .acknowledgment-box h3 {{
                color: #92400e;
                margin-top: 0;
            }}
            .signature-section {{
                margin-top: 60px;
                display: flex;
                justify-content: space-between;
            }}
            .signature-box {{
                text-align: center;
                width: 45%;
            }}
            .signature-line {{
                border-top: 2px solid #333;
                margin-top: 60px;
                padding-top: 10px;
            }}
            .print-btn {{
                position: fixed;
                top: 20px;
                left: 20px;
                background: #2563eb;
                color: white;
                border: none;
                padding: 12px 24px;
                border-radius: 8px;
                cursor: pointer;
                font-size: 16px;
                font-weight: bold;
            }}
            .print-btn:hover {{
                background: #1d4ed8;
            }}
            @media print {{
                .print-btn {{ display: none; }}
                body {{ padding: 20px; }}
            }}
        </style>
    </head>
    <body>
        <button class="print-btn" onclick="window.print()">🖨️ طباعة</button>
        
        <div class="header">
            <h1>نظام إدارة الاختبارات</h1>
            <h2>Examination Management System</h2>
            <h2>إقرار المتدرب بالاطلاع على تعليمات الاختبار</h2>
        </div>
        
        <div class="info-box">
            <h3>📋 بيانات المتدرب</h3>
            <div class="info-row">
                <strong>الاسم الكامل:</strong>
                <span>{trainee.full_name}</span>
            </div>
            <div class="info-row">
                <strong>الرقم التدريبي:</strong>
                <span>{trainee.trainee_id}</span>
            </div>
            <div class="info-row">
                <strong>التخصص:</strong>
                <span>{trainee.specialization}</span>
            </div>
            <div class="info-row">
                <strong>رقم الجوال:</strong>
                <span>{trainee.phone or '-'}</span>
            </div>
            <div class="info-row">
                <strong>البريد الإلكتروني:</strong>
                <span>{trainee.email or '-'}</span>
            </div>
        </div>
        
        <div class="info-box">
            <h3>📅 بيانات جلسة الاختبار</h3>
            <div class="info-row">
                <strong>المقرر:</strong>
                <span>{session.course_name}</span>
            </div>
            <div class="info-row">
                <strong>التاريخ:</strong>
                <span>{session.session_date.strftime('%Y-%m-%d')}</span>
            </div>
            <div class="info-row">
                <strong>الوقت:</strong>
                <span>{session.session_time.strftime('%H:%M')}</span>
            </div>
            <div class="info-row">
                <strong>المعمل/القاعة:</strong>
                <span>{session.location}</span>
            </div>
            <div class="info-row">
                <strong>رقم المحاولة:</strong>
                <span>{trainee.registration_order}</span>
            </div>
            <div class="info-row">
                <strong>تاريخ التسجيل:</strong>
                <span>{trainee.registered_at.strftime('%Y-%m-%d %H:%M')}</span>
            </div>
        </div>
        
        <div class="acknowledgment-box">
            <h3>✅ الإقرار والتعهد</h3>
            <p style="font-size: 16px; line-height: 2;">
                أقر أنا الموقع أدناه، <strong>{trainee.full_name}</strong>، 
                بأنني اطلعت على كافة تعليمات الاختبار النهائي (الذاتي) الخاصة بمقرر 
                <strong>{session.course_name}</strong>، وأتعهد بالالتزام التام بها، 
                بما في ذلك:
            </p>
            <ul style="font-size: 15px; line-height: 2;">
                <li>الحضور قبل الموعد المحدد بعشر دقائق على الأقل</li>
                <li>إحضار الهوية الوطنية الأصلية أو إبرازها عبر تطبيق توكلنا</li>
                <li>التأكد من صلاحية بيانات الدخول لمنصة تقني</li>
                <li>الالتزام بالنزاهة الأكاديمية وعدم استخدام أي مصادر خارجية</li>
                <li>التأكد من إرسال الاختبار نهائياً قبل الخروج</li>
            </ul>
            <p style="font-size: 14px; color: #92400e; margin-top: 15px;">
                <strong>تنبيه:</strong> أقر بأنني في حال عدم الحضور في الموعد المحدد دون عذر رسمي، 
                سأُعد متغيباً ومرصوداً لي درجة الصفر.
            </p>
        </div>
        
        <div class="signature-section">
            <div class="signature-box">
                <div class="signature-line">
                    <strong>توقيع المتدرب</strong><br>
                    {trainee.full_name}
                </div>
            </div>
            <div class="signature-box">
                <div class="signature-line">
                    <strong>التاريخ</strong><br>
                    {datetime.now().strftime('%Y-%m-%d')}
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    
    response = make_response(html_content)
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    return response


# ═══════════════════════════════════════════════════════
# مسارات المسؤول
# ═══════════════════════════════════════════════════════

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if current_user.is_authenticated:
        return redirect(url_for('admin_dashboard'))
    form = LoginForm()
    if form.validate_on_submit():
        admin = Admin.query.filter_by(username=form.username.data).first()
        if admin and admin.check_password(form.password.data):
            login_user(admin)
            flash(f'مرحباً {admin.full_name}!', 'success')
            return redirect(url_for('admin_dashboard'))
        flash('بيانات الدخول غير صحيحة', 'danger')
    return render_template('admin/login.html', form=form)


@app.route('/admin/logout')
@login_required
def admin_logout():
    logout_user()
    flash('تم تسجيل الخروج', 'info')
    return redirect(url_for('admin_login'))


@app.route('/admin')
@login_required
def admin_dashboard():
    sessions = TestSession.query.order_by(TestSession.session_date).all()
    total_trainees = Trainee.query.count()
    total_sessions = len(sessions)
    full_sessions = sum(1 for s in sessions if s.is_full)
    total_enrollments = CourseEnrollment.query.count()
    total_graded = Grade.query.count()
    
    return render_template('admin/dashboard.html',
                         sessions=sessions, total_trainees=total_trainees,
                         total_sessions=total_sessions, full_sessions=full_sessions,
                         total_enrollments=total_enrollments, total_graded=total_graded)


@app.route('/admin/sessions')
@login_required
def admin_sessions():
    sessions = TestSession.query.order_by(
        TestSession.session_date, TestSession.session_time
    ).all()
    return render_template('admin/sessions.html', sessions=sessions)


@app.route('/admin/sessions/new', methods=['GET', 'POST'])
@login_required
def admin_session_new():
    form = SessionForm()
    
    if request.method == 'POST':
        if form.validate_on_submit():
            try:
                session_date = form.session_date.data
                session_time = form.session_time.data
                location = form.location.data
                
                # ✅ فحص التعارض الزماني والمكاني
                is_conflict, conflicting_session = check_time_location_conflict(
                    session_date, session_time, location
                )
                
                if is_conflict:
                    flash(f'⚠️ لا يمكن تسجيل الجلسة: المعمل "{conflicting_session.location}" مخصص لجلسة أخرى في هذا الوقت ({conflicting_session.course_name} - {conflicting_session.specialization})', 'danger')
                    return redirect(url_for('admin_session_new'))
                
                session = TestSession(
                    course_name=form.course_name.data,
                    specialization=form.specialization.data,
                    session_date=session_date,
                    session_time=session_time,
                    location=location,
                    max_capacity=form.max_capacity.data
                )
                db.session.add(session)
                db.session.commit()
                flash('✅ تم إنشاء الجلسة بنجاح', 'success')
                return redirect(url_for('admin_sessions'))
            except Exception as e:
                db.session.rollback()
                flash(f'❌ خطأ: {str(e)}', 'danger')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    flash(f'❌ {error}', 'danger')
    
    return render_template('admin/session_form.html', form=form, title='إضافة جلسة')


@app.route('/admin/sessions/<int:session_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_session_edit(session_id):
    session = TestSession.query.get_or_404(session_id)
    form = SessionForm(obj=session)
    
    if request.method == 'POST':
        if form.validate_on_submit():
            try:
                session_date = form.session_date.data
                session_time = form.session_time.data
                location = form.location.data
                
                # ✅ فحص التعارض مع استثناء الجلسة الحالية
                is_conflict, conflicting_session = check_time_location_conflict(
                    session_date, session_time, location, exclude_id=session_id
                )
                
                if is_conflict:
                    flash(f'⚠️ لا يمكن تحديث الجلسة: المعمل "{conflicting_session.location}" مخصص لجلسة أخرى في هذا الوقت', 'danger')
                    return redirect(url_for('admin_session_edit', session_id=session_id))
                
                session.course_name = form.course_name.data
                session.specialization = form.specialization.data
                session.session_date = session_date
                session.session_time = session_time
                session.location = location
                session.max_capacity = form.max_capacity.data
                db.session.commit()
                flash('✅ تم التحديث', 'success')
                return redirect(url_for('admin_sessions'))
            except Exception as e:
                db.session.rollback()
                flash(f'❌ خطأ: {str(e)}', 'danger')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    flash(f'❌ {error}', 'danger')
    
    return render_template('admin/session_form.html', form=form, session=session, title='تعديل جلسة')


@app.route('/admin/sessions/<int:session_id>/delete', methods=['POST'])
@login_required
def admin_session_delete(session_id):
    session = TestSession.query.get_or_404(session_id)
    try:
        db.session.delete(session)
        db.session.commit()
        flash('✅ تم حذف الجلسة', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ خطأ: {str(e)}', 'danger')
    return redirect(url_for('admin_sessions'))


@app.route('/admin/sessions/<int:session_id>/attendance', methods=['GET', 'POST'])
@login_required
def admin_session_attendance(session_id):
    session = TestSession.query.get_or_404(session_id)
    
    if request.method == 'POST':
        for trainee in session.trainees:
            status = request.form.get(f'attendance_{trainee.id}')
            if status:
                trainee.attendance_status = status
        db.session.commit()
        flash('✅ تم تحديث الحضور', 'success')
        return redirect(url_for('admin_session_attendance', session_id=session_id))
    
    return render_template('admin/attendance.html', session=session)


@app.route('/admin/sessions/<int:session_id>/grades', methods=['GET', 'POST'])
@login_required
def admin_session_grades(session_id):
    session = TestSession.query.get_or_404(session_id)
    
    if request.method == 'POST':
        for trainee in session.trainees:
            score_str = request.form.get(f'score_{trainee.id}')
            attempt_str = request.form.get(f'attempt_{trainee.id}', '1')
            notes = request.form.get(f'notes_{trainee.id}', '')
            
            if score_str:
                try:
                    score = float(score_str)
                    attempt = int(attempt_str)
                    
                    existing_grade = Grade.query.filter_by(
                        trainee_id=trainee.id,
                        session_id=session_id,
                        attempt_number=attempt
                    ).first()
                    
                    if existing_grade:
                        existing_grade.score = score
                        existing_grade.notes = notes
                    else:
                        new_grade = Grade(
                            trainee_id=trainee.id,
                            session_id=session_id,
                            score=score,
                            attempt_number=attempt,
                            notes=notes,
                            graded_by=current_user.id
                        )
                        db.session.add(new_grade)
                    
                except ValueError:
                    flash(f'❌ درجة غير صحيحة للمتدرب {trainee.full_name}', 'danger')
        
        db.session.commit()
        flash('✅ تم رصد الدرجات', 'success')
        return redirect(url_for('admin_session_grades', session_id=session_id))
    
    return render_template('admin/grades.html', session=session)


@app.route('/admin/enrollments')
@login_required
def admin_enrollments():
    course_filter = request.args.get('course', '')
    spec_filter = request.args.get('specialization', '')
    
    query = CourseEnrollment.query
    if course_filter:
        query = query.filter_by(course_name=course_filter)
    if spec_filter:
        query = query.filter_by(specialization=spec_filter)
    
    enrollments = query.order_by(CourseEnrollment.course_name, CourseEnrollment.full_name).all()
    
    return render_template('admin/course_enrollments.html',
                         enrollments=enrollments, courses=COURSES,
                         specializations=SPECIALIZATIONS,
                         current_course=course_filter, current_spec=spec_filter)


@app.route('/admin/enrollments/upload', methods=['GET', 'POST'])
@login_required
def admin_enrollments_upload():
    form = CourseEnrollmentUploadForm()
    
    if form.validate_on_submit():
        course_name = form.course_name.data
        csv_file = form.csv_file.data
        
        results = import_course_enrollments_from_csv(
            csv_file.stream, course_name, current_user.id
        )
        
        if results['success'] > 0:
            flash(f'✅ تم استيراد {results["success"]} متدرب', 'success')
        if results['skipped'] > 0:
            flash(f'⚠️ تم تخطي {results["skipped"]} سجل', 'warning')
        if results['errors']:
            for error in results['errors'][:5]:
                flash(f'❌ {error}', 'danger')
        
        return redirect(url_for('admin_enrollments'))
    
    return render_template('admin/enrollment_upload.html', form=form, courses=COURSES)


@app.route('/admin/enrollments/delete/<int:enrollment_id>', methods=['POST'])
@login_required
def admin_enrollment_delete(enrollment_id):
    enrollment = CourseEnrollment.query.get_or_404(enrollment_id)
    db.session.delete(enrollment)
    db.session.commit()
    flash('تم الحذف', 'success')
    return redirect(url_for('admin_enrollments'))


@app.route('/admin/reports')
@login_required
def admin_reports():
    sessions = TestSession.query.order_by(TestSession.session_date).all()
    return render_template('admin/reports.html', sessions=sessions)


@app.route('/admin/reports/<int:session_id>/csv')
@login_required
def admin_report_csv(session_id):
    session = TestSession.query.get_or_404(session_id)
    csv_content = generate_session_report_csv(session)
    filename = f"report_{session_id}_{session.session_date}.csv"
    
    return Response(
        csv_content,
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


@app.route('/admin/reports/<int:session_id>/print')
@login_required
def admin_report_print(session_id):
    session = TestSession.query.get_or_404(session_id)
    return render_template('admin/report_print.html', session=session)


if __name__ == '__main__':
    init_db()
    print("\n" + "="*70)
    print("🎓 نظام إدارة الاختبارات - الإصدار المحدث")
    print("="*70)
    print("🌐 http://127.0.0.1:5000")
    print("🔐 http://127.0.0.1:5000/admin/login")
    print("👤 admin / admin123")
    print("="*70 + "\n")
    app.run(debug=True, host='0.0.0.0', port=5000)