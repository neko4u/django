#!/bin/bash
CFG=/opt/config/django/project1settings.json
FROM=$(python -c "import json;m=json.load(open('$CFG'))['mail'];b=m.get('_resend_backup') or {};print(b.get('from_email') or m.get('resend_from_email',''))")
KEY=$(python -c "import json;m=json.load(open('$CFG'))['mail'];b=m.get('_resend_backup') or {};print(b.get('smtp_password') or m.get('resend_smtp_password',''))")
echo "$(date '+%F %T')  from=$FROM"
curl -s -o /tmp/resend_api.json -w "api   HTTP %{http_code}\n" -X POST https://api.resend.com/emails \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d "{\"from\":\"$FROM\",\"to\":[\"$FROM\"],\"subject\":\"delivery test\",\"text\":\"hi\"}"
cat /tmp/resend_api.json; echo
FROM="$FROM" KEY="$KEY" python - <<'PYEOF'
import os, smtplib
from email.mime.text import MIMEText
f, k = os.environ['FROM'], os.environ['KEY']
m = MIMEText('delivery test', 'plain', 'utf-8')
m['Subject'] = 'delivery test'
m['From'] = f
m['To'] = f
step = 'connect'
try:
    s = smtplib.SMTP_SSL('smtp.resend.com', 465, timeout=30)
    step = 'login'
    c, r = s.login('resend', k)
    print('smtp  login  %s %s' % (c, r.decode() if isinstance(r, bytes) else r))
    step = 'send'
    s.sendmail(f, [f], m.as_string())
    print('smtp  send   250 OK')
    s.quit()
except smtplib.SMTPResponseException as e:
    err = e.smtp_error.decode('utf-8', 'replace') if isinstance(e.smtp_error, bytes) else e.smtp_error
    print('smtp  %s  %s %s' % (step, e.smtp_code, err))
except Exception as e:
    print('smtp  %s  %s %s' % (step, type(e).__name__, e))
PYEOF
