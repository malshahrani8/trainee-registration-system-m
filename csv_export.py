import csv
import io
from datetime import datetime

def generate_session_report_csv(session):
    """توليد تقرير CSV لجلسة معينة"""
    output = io.StringIO()
    
    # إضافة BOM لدعم العربية في Excel
    output.write('\ufeff')
    
    writer = csv.writer(output)
    
    # رأس التقرير
    writer.writerow(['المؤسسة العامة للتدريب التقني والمهني - TVTC'])
    writer.writerow([f'تقرير جلسة اختبار - {session.course_name}'])
    writer.writerow([])
    
    # معلومات الجلسة
    writer.writerow(['تاريخ الجلسة:', session.session_date.strftime('%Y-%m-%d')])
    writer.writerow(['وقت الجلسة:', session.session_time.strftime('%H:%M')])
    writer.writerow(['رقم المعمل:', session.location])
    writer.writerow(['عدد المسجلين:', f'{session.current_count} / {session.max_capacity}'])
    writer.writerow(['تاريخ التقرير:', datetime.now().strftime('%Y-%m-%d %H:%M')])
    writer.writerow([])
    
    # رأس الجدول
    writer.writerow([
        '#',
        'الرقم التدريبي',
        'الاسم الكامل',
        'البريد الإلكتروني',
        'رقم الجوال',
        'التخصص',
        'الحالة',
        'تاريخ التسجيل'
    ])
    
    # البيانات
    for idx, trainee in enumerate(session.trainees, 1):
        writer.writerow([
            idx,
            trainee.trainee_id,
            trainee.full_name,
            trainee.email,
            trainee.phone,
            trainee.specialization,
            'حضر' if trainee.attendance_status == 'attended' else 'لم يحضر',
            trainee.registered_at.strftime('%Y-%m-%d %H:%M')
        ])
    
    output.seek(0)
    return output.getvalue()