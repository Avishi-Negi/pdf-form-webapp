from flask import Flask, render_template, request, send_file
import os, shutil, tempfile, re, zipfile
from datetime import datetime
from pdfrw import PdfReader, PdfWriter, PageMerge
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import simpleSplit
from werkzeug.utils import secure_filename
import pandas as pd  # Excel support added

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Convert date to MM.DD.YYYY format
def format_date_mmddyyyy(raw_date):
    if not raw_date:
        return ''
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(str(raw_date), fmt).strftime("%m.%d.%Y")
        except:
            continue
    return str(raw_date)

def overlay_data(input_pdf, output_pdf, data_dict):
    temp_overlay = os.path.join(tempfile.gettempdir(), "temp_overlay.pdf")
    c = canvas.Canvas(temp_overlay, pagesize=letter)

    c.setFont("Helvetica", 10)
    if 'Date' in data_dict:
        c.drawString(175, 730, data_dict['Date'])
    if 'Appt Time' in data_dict:
        c.setFont("Helvetica", 6.5)
        c.drawString(309, 730, data_dict['Appt Time'][:40])
    c.setFont("Helvetica", 10)
    if 'Patient Name' in data_dict:
        c.drawString(450, 730, data_dict['Patient Name'])
    if 'DOB' in data_dict:
        c.drawString(370, 670, data_dict['DOB'])
    if 'CC' in data_dict:
        c.drawString(130, 620, data_dict['CC'][:50])
    c.setFont("Helvetica", 6.5)
    if 'Primary Ins' in data_dict:
        lines = simpleSplit(data_dict['Primary Ins'], "Helvetica", 8, 150)
        for i, line in enumerate(lines[:2]):
            c.drawString(73, 680 - i * 13, line)
    if 'Sec/Sup Ins' in data_dict:
        c.drawString(80, 650, data_dict['Sec/Sup Ins'])
    if 'Brief History' in data_dict:
        c.setFont("Helvetica", 9)
        lines = simpleSplit(data_dict['Brief History'], "Helvetica", 9, 450)
        for i, line in enumerate(lines[:5]):
            c.drawString(75, 570 - i * 13, line)

    meds = data_dict.get('Medications', [])
    for i, med in enumerate(meds[:4]):
        line = f"Fill Date: {med['date']}  Med: {med['name']}  Qty: {med['qty']}  Refill [{med['refill']}]"
        c.drawString(60, 500 - i * 15, line[:90])

    c.save()

    try:
        template = PdfReader(input_pdf)
    except:
        raise ValueError("⚠️ Unable to read the uploaded PDF. Please re-save it using 'Print to PDF' and try again.")

    overlay = PdfReader(temp_overlay)
    for page, ol in zip(template.pages, overlay.pages):
        PageMerge(page).add(ol).render()
    PdfWriter(output_pdf, trailer=template).write()

def process_csv_or_excel(file_path, pdf_template_path, output_dir):
    ext = os.path.splitext(file_path)[1].lower()
    if ext == '.csv':
        df = pd.read_csv(file_path)
    elif ext in ['.xlsx', '.xls']:
        df = pd.read_excel(file_path)
    else:
        raise ValueError("❌ Unsupported file type. Only .csv, .xls, .xlsx are supported.")

    records = df.to_dict(orient='records')

    def parse_time(row):
        t = str(row.get('Appt Time', '')).strip()
        try:
            return datetime.strptime(t, "%I:%M %p")
        except:
            return datetime.min

    records.sort(key=parse_time)

    for row in records:
        meds = []
        if row.get('Medications'):
            for part in str(row['Medications']).split(';'):
                if '|' in part:
                    d, n, q, r = part.split('|')
                    meds.append({'date': d.strip(), 'name': n.strip(), 'qty': q.strip(), 'refill': r.strip()})

        patient_name = row.get('Patient Name', 'unknown')
        safe_name = re.sub(r'[\\/*?:"<>|,]', '', patient_name).replace(' ', '_')

        raw_date = row.get('\ufeffDate', '') or row.get('Date', '')
        raw_dob = row.get('DOB', '')

        formatted_date = format_date_mmddyyyy(raw_date)
        formatted_dob = format_date_mmddyyyy(raw_dob)

        data = {
            'Date': formatted_date,
            'Appt Time': row.get('Appt Time', ''),
            'Patient Name': patient_name,
            'DOB': formatted_dob,
            'CC': row.get('CC', ''),
            'Primary Ins': row.get('Primary Ins', ''),
            'Sec/Sup Ins': row.get('Sec/Sup Ins', ''),
            'Brief History': row.get('Brief History', ''),
            'Medications': meds
        }

        output_pdf = os.path.join(output_dir, f"{safe_name}.pdf")
        overlay_data(pdf_template_path, output_pdf, data)

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        try:
            csv_file = request.files['csv_file']
            pdf_template = request.files['pdf_template']

            if not csv_file or not pdf_template:
                return "❌ Missing files. Please upload both CSV/Excel and PDF.", 400

            csv_path = os.path.join(UPLOAD_FOLDER, secure_filename(csv_file.filename))
            pdf_path = os.path.join(UPLOAD_FOLDER, secure_filename(pdf_template.filename))
            csv_file.save(csv_path)
            pdf_template.save(pdf_path)

            output_dir = os.path.join(tempfile.gettempdir(), "pdf_output")
            if os.path.exists(output_dir):
                shutil.rmtree(output_dir)
            os.makedirs(output_dir)

            process_csv_or_excel(csv_path, pdf_path, output_dir)

            zip_path = os.path.join(UPLOAD_FOLDER, "filled_forms.zip")
            with zipfile.ZipFile(zip_path, 'w') as zipf:
                for fname in os.listdir(output_dir):
                    full_path = os.path.join(output_dir, fname)
                    zipf.write(full_path, arcname=fname)

            return send_file(zip_path, as_attachment=True)

        except Exception as e:
            import traceback
            print(traceback.format_exc())
            return f"<h3 style='color:red;'>❌ Error: {str(e)}</h3>"

    return render_template('index.html')

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
