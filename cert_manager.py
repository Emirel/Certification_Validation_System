from datetime import datetime
import hashlib
import hmac
import io
import sqlite3
import uuid
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas


class CertificateManager:

  def __init__(
      self,
      secret_key: str = "SUPER_SECRET_KEY_CONSULTING_2026",
      db_path: str = "certificates.db",
  ):
    self.secret_key = secret_key.encode("utf-8")
    self.db_path = db_path
    self._init_db()

  def _init_db(self):
    with sqlite3.connect(self.db_path) as conn:
      cursor = conn.cursor()
      cursor.execute("""
                CREATE TABLE IF NOT EXISTS certificates (
                    cert_id TEXT PRIMARY KEY,
                    cert_number TEXT UNIQUE NOT NULL,
                    recipient_name TEXT NOT NULL,
                    program_name TEXT NOT NULL,
                    cert_type TEXT NOT NULL,
                    organizer TEXT NOT NULL,
                    issue_date TEXT NOT NULL,
                    expiry_date TEXT,
                    grade_or_score TEXT,
                    signature TEXT NOT NULL,
                    is_revoked INTEGER DEFAULT 0,
                    revocation_reason TEXT
                )
            """)
      conn.commit()

  def _generate_signature(
      self,
      cert_id: str,
      cert_number: str,
      name: str,
      program: str,
      issue_date: str,
  ) -> str:
    payload = f"{cert_id}|{cert_number}|{name}|{program}|{issue_date}"
    return hmac.new(
        self.secret_key, payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()

  def issue_certificate(
      self,
      cert_number: str,
      recipient_name: str,
      program_name: str,
      cert_type: str,
      organizer: str,
      issue_date: str,
      expiry_date: str = None,
      grade_or_score: str = "Kompeten",
  ) -> dict:
    cert_id = f"CRT-{uuid.uuid4().hex[:10].upper()}"
    signature = self._generate_signature(
        cert_id, cert_number, recipient_name, program_name, issue_date
    )

    with sqlite3.connect(self.db_path) as conn:
      cursor = conn.cursor()
      cursor.execute(
          """
                INSERT INTO certificates (
                    cert_id, cert_number, recipient_name, program_name,
                    cert_type, organizer, issue_date, expiry_date,
                    grade_or_score, signature, is_revoked
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
          (
              cert_id,
              cert_number,
              recipient_name,
              program_name,
              cert_type,
              organizer,
              issue_date,
              expiry_date,
              grade_or_score,
              signature,
          ),
      )
      conn.commit()

    return self.verify_certificate(cert_id)["data"]

  def verify_certificate(self, identifier: str) -> dict:
    """Verifikasi berdasarkan cert_id (CRT-XXXX) atau nomor registrasi resmi."""
    with sqlite3.connect(self.db_path) as conn:
      conn.row_factory = sqlite3.Row
      cursor = conn.cursor()
      cursor.execute(
          """
                SELECT * FROM certificates 
                WHERE cert_id = ? OR cert_number = ?
            """,
          (identifier.strip(), identifier.strip()),
      )
      row = cursor.fetchone()

    if not row:
      return {
          "status": "NOT_FOUND",
          "is_valid": False,
          "message": (
              "Data sertifikat tidak ditemukan di pangkalan data resmi."
          ),
          "data": None,
      }

    data = dict(row)

    # 1. Pengecekan integritas tanda tangan digital
    expected_sig = self._generate_signature(
        data["cert_id"],
        data["cert_number"],
        data["recipient_name"],
        data["program_name"],
        data["issue_date"],
    )
    if not hmac.compare_digest(data["signature"], expected_sig):
      return {
          "status": "TAMPERED",
          "is_valid": False,
          "message": "Peringatan: Integritas data sertifikat tidak valid.",
          "data": data,
      }

    # 2. Pengecekan status pencabutan (revocation)
    if data["is_revoked"] == 1:
      return {
          "status": "REVOKED",
          "is_valid": False,
          "message": (
              f"Sertifikat telah dicabut. Alasan:"
              f" {data.get('revocation_reason', '-')}"
          ),
          "data": data,
      }

    # 3. Pengecekan masa berlaku
    if data["expiry_date"]:
      exp_dt = datetime.strptime(data["expiry_date"], "%Y-%m-%d").date()
      if datetime.now().date() > exp_dt:
        return {
            "status": "EXPIRED",
            "is_valid": False,
            "message": (
                "Masa berlaku sertifikasi telah berakhir pada"
                f" {data['expiry_date']}."
            ),
            "data": data,
        }

    return {
        "status": "VALID",
        "is_valid": True,
        "message": (
            "Sertifikat sah, aktif, dan terverifikasi di sistem pangkalan data."
        ),
        "data": data,
    }

  def revoke_certificate(self, identifier: str, reason: str) -> bool:
    with sqlite3.connect(self.db_path) as conn:
      cursor = conn.cursor()
      cursor.execute(
          """
                UPDATE certificates 
                SET is_revoked = 1, revocation_reason = ? 
                WHERE cert_id = ? OR cert_number = ?
            """,
          (reason, identifier, identifier),
      )
      conn.commit()
      return cursor.rowcount > 0

  def generate_pdf(self, cert_data: dict, verification_url: str) -> bytes:
    """Membuat file PDF Sertifikat A4 Landscape beresolusi tinggi dengan QR Code verifikasi."""
    buffer = io.BytesIO()
    width, height = landscape(A4)
    c = canvas.Canvas(buffer, pagesize=landscape(A4))

    # Border luar (Navy)
    c.setStrokeColor(colors.HexColor("#0F294A"))
    c.setLineWidth(4)
    c.rect(20, 20, width - 40, height - 40)

    # Border dalam (Emas)
    c.setStrokeColor(colors.HexColor("#C59B27"))
    c.setLineWidth(1.5)
    c.rect(26, 26, width - 52, height - 52)

    # Header Institusi
    c.setFont("Helvetica-Bold", 13)
    c.setFillColor(colors.HexColor("#4A5568"))
    c.drawCentredString(
        width / 2.0, height - 65, cert_data["organizer"].upper()
    )

    # Judul Sertifikat
    c.setFont("Helvetica-Bold", 26)
    c.setFillColor(colors.HexColor("#0F294A"))
    title_text = (
        "SERTIFIKAT KOMPETENSI"
        if cert_data["cert_type"].lower() == "sertifikasi"
        else "SERTIFIKAT KELULUSAN"
    )
    c.drawCentredString(width / 2.0, height - 105, title_text)

    # Nomor Registrasi
    c.setFont("Helvetica", 10)
    c.setFillColor(colors.HexColor("#718096"))
    c.drawCentredString(
        width / 2.0,
        height - 125,
        f"Nomor Registrasi: {cert_data['cert_number']}",
    )

    # Narasi Penerima
    c.setFont("Helvetica-Oblique", 12)
    c.setFillColor(colors.HexColor("#4A5568"))
    c.drawCentredString(width / 2.0, height - 165, "Diberikan kepada:")

    # Nama Peserta
    c.setFont("Helvetica-Bold", 24)
    c.setFillColor(colors.HexColor("#1A202C"))
    c.drawCentredString(width / 2.0, height - 200, cert_data["recipient_name"])

    # Keterangan Program
    c.setFont("Helvetica", 12)
    c.setFillColor(colors.HexColor("#4A5568"))
    c.drawCentredString(
        width / 2.0,
        height - 235,
        "Telah memenuhi seluruh standar evaluasi dan menyelesaikan program"
        " pelatihan:",
    )

    # Nama Program / Pelatihan
    c.setFont("Helvetica-Bold", 17)
    c.setFillColor(colors.HexColor("#1A365D"))
    c.drawCentredString(width / 2.0, height - 265, cert_data["program_name"])

    if cert_data.get("grade_or_score"):
      c.setFont("Helvetica-Bold", 11)
      c.setFillColor(colors.HexColor("#2D3748"))
      c.drawCentredString(
          width / 2.0, height - 290, f"Predikat: {cert_data['grade_or_score']}"
      )

    # Metadata Pojok Kiri Bawah
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor("#718096"))
    c.drawString(60, 115, f"Tanggal Terbit : {cert_data['issue_date']}")
    expiry_str = cert_data.get("expiry_date") or "Seumur Hidup"
    c.drawString(60, 100, f"Masa Berlaku   : {expiry_str}")
    c.drawString(60, 85, f"ID Sistem      : {cert_data['cert_id']}")

    # QR Code Otomatis Pojok Kanan Bawah
    q = qr.QrCodeWidget(verification_url)
    b = q.getBounds()
    qw, qh = b[2] - b[0], b[3] - b[1]
    qr_size = 75
    d = Drawing(
        qr_size, qr_size, transform=[qr_size / qw, 0, 0, qr_size / qh, 0, 0]
    )
    d.add(q)
    renderPDF.draw(d, c, width - 145, 65)

    c.setFont("Helvetica", 7.5)
    c.drawCentredString(width - 108, 55, "Pindai untuk Verifikasi")

    # Garis Tanda Tangan Tengah Bawah
    c.setStrokeColor(colors.HexColor("#A0AEC0"))
    c.setLineWidth(1)
    c.line(width / 2.0 - 90, 85, width / 2.0 + 90, 85)
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(colors.HexColor("#2D3748"))
    c.drawCentredString(width / 2.0, 72, "Authorized Signature")
    c.setFont("Helvetica", 8.5)
    c.setFillColor(colors.HexColor("#718096"))
    c.drawCentredString(width / 2.0, 60, cert_data["organizer"])

    c.save()
    buffer.seek(0)
    return buffer.getvalue()