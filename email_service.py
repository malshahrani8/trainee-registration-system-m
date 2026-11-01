from flask_mail import Mail, Message
from flask import render_template

mail = Mail()

def send_confirmation_email(trainee, session):
    """إرسال بريد تأكيد التسجيل للمتدرب"""
    try:
        msg = Message(
            subject='تأكيد التسجيل في اختبار مقدمة تطبيقات الحاسب - الكلية التقنية ببيشة',
            recipients=[trainee.email],
            sender='BCT-registration@example.com'
        )
        
        # المحتوى HTML
        msg.html = render_template(
            'emails/confirmation.html',
            trainee=trainee,
            session=session
        )
        
        # محتوى نصي احتياطي
        msg.body = f"""
مرحباً {trainee.full_name}،

تم تأكيد تسجيلك بنجاح في اختبار  "مقدمة تطبيقات الحاسب".

📅 تاريخ الجلسة: {session.session_date.strftime('%Y-%m-%d')}
⏰ وقت الجلسة: {session.session_time.strftime('%H:%M')}
🏢 رقم المعمل: {session.location}
🔢 الرقم التدريبي: {trainee.trainee_id}

نتمنى لك التوفيق.
الكلية التقنية ببيشة - BCT
        """
        
        mail.send(msg)
        return True, 'تم إرسال بريد التأكيد بنجاح'
    except Exception as e:
        return False, f'فشل إرسال البريد: {str(e)}'