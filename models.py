from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, date, time
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

# ═══════════════════════════════════════════════════════
# الثوابت
# ═══════════════════════════════════════════════════════

SPECIALIZATIONS = [
    ('دعم فني', 'دعم فني'),
    ('شبكات الحاسب', 'شبكات الحاسب'),
    ('محاسبة', 'محاسبة'),
    ('إدارة مكتبية', 'إدارة مكتبية'),
    ('ميكانيكا', 'ميكانيكا'),
    ('إلكترونيات', 'إلكترونيات'),
]

COURSES = [
    ('مقدمة تطبيقات الحاسب', 'مقدمة تطبيقات الحاسب'),
    ('أساسيات البرمجة', 'أساسيات البرمجة'),
    ('قواعد البيانات', 'قواعد البيانات'),
    ('أنظمة التشغيل', 'أنظمة التشغيل'),
    ('أمن الشبكات', 'أمن الشبكات'),
]

CSV_SPECIALIZATION_MAPPING = {
    'تقنية الدعم الفني للحاسب': 'دعم فني',
    'تقنية شبكات الحاسب': 'شبكات الحاسب',
    'تقنيات محاسبية': 'محاسبة',
    'تقنيات الاعمال المكتبية': 'إدارة مكتبية',
    'تقنية المحركات ومركبات': 'ميكانيكا',
    'تقنية الإلكترونيات وأنظمة التح': 'إلكترونيات',
}

ATTENDANCE_STATUS = [
    ('pending', 'لم يحضر بعد'),
    ('attended', 'حضر'),
    ('missed', 'غائب'),
]


class Admin(UserMixin, db.Model):
    __tablename__ = 'admins'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class CourseEnrollment(db.Model):
    """تسجيل المتدربين في المقررات (من CSV)"""
    __tablename__ = 'course_enrollments'
    
    id = db.Column(db.Integer, primary_key=True)
    trainee_id = db.Column(db.String(20), nullable=False, index=True)
    full_name = db.Column(db.String(100), nullable=False)
    course_name = db.Column(db.String(200), nullable=False, index=True)
    specialization = db.Column(db.String(50), nullable=False, index=True)
    phone = db.Column(db.String(15))
    email = db.Column(db.String(120))
    enrolled_by = db.Column(db.Integer, db.ForeignKey('admins.id'))
    enrolled_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        db.UniqueConstraint('trainee_id', 'course_name', name='unique_trainee_course'),
    )
    
    admin = db.relationship('Admin', backref='enrollments')


class TestSession(db.Model):
    """جلسة الاختبار"""
    __tablename__ = 'test_sessions'
    
    id = db.Column(db.Integer, primary_key=True)
    course_name = db.Column(db.String(200), nullable=False, index=True)
    specialization = db.Column(db.String(50), nullable=False, index=True)
    session_date = db.Column(db.Date, nullable=False)
    session_time = db.Column(db.Time, nullable=False)
    location = db.Column(db.String(100), nullable=False)
    max_capacity = db.Column(db.Integer, default=20, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # ✅ العلاقة مع cascade delete
    trainees = db.relationship('Trainee', backref='session', lazy=True, cascade='all, delete-orphan')
    grades = db.relationship('Grade', backref='session', lazy=True, cascade='all, delete-orphan')
    
    @property
    def current_count(self):
        return len(self.trainees)
    
    @property
    def is_full(self):
        return self.current_count >= self.max_capacity
    
    @property
    def available_seats(self):
        return self.max_capacity - self.current_count
    
    @property
    def display_datetime(self):
        return f"{self.session_date.strftime('%Y-%m-%d')} الساعة {self.session_time.strftime('%H:%M')}"
    
    @property
    def status_badge(self):
        if self.is_full:
            return '<span class="badge badge-danger">مكتملة</span>'
        return f'<span class="badge badge-success">متاحة ({self.available_seats} مقعد)</span>'


class Trainee(db.Model):
    """تسجيل المتدرب في جلسة اختبار"""
    __tablename__ = 'trainees'
    
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    trainee_id = db.Column(db.String(20), nullable=False, index=True)
    phone = db.Column(db.String(15))
    email = db.Column(db.String(120))
    specialization = db.Column(db.String(50), nullable=False)
    
    session_id = db.Column(db.Integer, db.ForeignKey('test_sessions.id'), nullable=False)
    attendance_status = db.Column(db.String(20), default='pending', nullable=False)
    registration_order = db.Column(db.Integer, nullable=False)
    
    registered_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # ✅ العلاقة مع grades
    grades = db.relationship('Grade', backref='trainee', lazy=True, cascade='all, delete-orphan')
    
    __table_args__ = (
        db.UniqueConstraint('trainee_id', 'session_id', name='unique_trainee_session'),
    )
    
    @property
    def status_badge(self):
        if self.attendance_status == 'attended':
            return '<span class="badge badge-success">حضر</span>'
        elif self.attendance_status == 'missed':
            return '<span class="badge badge-danger">غائب</span>'
        return '<span class="badge badge-warning">لم يحضر</span>'
    
    @property
    def latest_grade(self):
        """أحدث درجة للمتدرب في هذه الجلسة"""
        if self.grades:
            return max(self.grades, key=lambda g: g.graded_at)
        return None
    
    @property
    def passed(self):
        """هل اجتاز المتدرب الاختبار؟"""
        latest = self.latest_grade
        return latest and latest.score >= 60


class Grade(db.Model):
    """🆕 جدول رصد الدرجات"""
    __tablename__ = 'grades'
    
    id = db.Column(db.Integer, primary_key=True)
    trainee_id = db.Column(db.Integer, db.ForeignKey('trainees.id'), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey('test_sessions.id'), nullable=False)
    score = db.Column(db.Float, nullable=False)  # من 100
    attempt_number = db.Column(db.Integer, nullable=False, default=1)  # المحاولة الأولى، الثانية، إلخ
    notes = db.Column(db.Text)
    graded_by = db.Column(db.Integer, db.ForeignKey('admins.id'))
    graded_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    grader = db.relationship('Admin', backref='graded_records')
    
    @property
    def passed(self):
        return self.score >= 60
    
    @property
    def score_badge(self):
        if self.score >= 60:
            return f'<span class="grade-display grade-pass">{self.score}</span>'
        return f'<span class="grade-display grade-fail">{self.score}</span>'