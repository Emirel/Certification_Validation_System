import os
from cert_manager import CertificateManager
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

app = FastAPI(
    title="Certificate Validation & Issuance API",
    version="1.0.0",
    description=(
        "Public API dan Portal Verifikasi Resmi Pelatihan & Sertifikasi."
    ),
)

# Sesuaikan BASE_URL dengan domain produksi Anda
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
manager = CertificateManager()


# --- Skema Data Pydantic ---
class CertificateIssueRequest(BaseModel):
  cert_number: str
  recipient_name: str
  program_name: str
  cert_type: str = "Pelatihan"  # 'Pelatihan' atau 'Sertifikasi'
  organizer: str = "PT Consulting & Training Indonesia"
  issue_date: str  # Format: YYYY-MM-DD
  expiry_date: str | None = None  # Format: YYYY-MM-DD (opsional)
  grade_or_score: str | None = "Sangat Baik (Kompeten)"


class RevokeRequest(BaseModel):
  reason: str


# ==========================================
# 1. REST API ENDPOINTS (Untuk Integrasi Sistem)
# ==========================================


@app.get(
    "/api/v1/verify/{identifier}",
    tags=["Public API"],
    summary="Verifikasi Status Sertifikat (JSON)",
)
def api_verify_certificate(identifier: str):
  """Mengecek keaslian dan status sertifikat.

  Dapat diakses oleh aplikasi pihak ketiga atau sistem HR.
  """
  result = manager.verify_certificate(identifier)
  if result["status"] == "NOT_FOUND":
    raise HTTPException(status_code=404, detail=result["message"])

  # Menyertakan link download PDF dan web verification
  if result["data"]:
    cert_id = result["data"]["cert_id"]
    result["pdf_url"] = f"{BASE_URL}/api/v1/certificates/{cert_id}/pdf"
    result["verification_url"] = f"{BASE_URL}/verify/{cert_id}"

  return result


@app.post(
    "/api/v1/certificates",
    tags=["Admin API"],
    summary="Terbitkan Sertifikat Baru",
)
def api_issue_certificate(req: CertificateIssueRequest):
  """Menerbitkan sertifikat ke dalam database dan menghasilkan ID unik."""
  try:
    cert = manager.issue_certificate(
        cert_number=req.cert_number,
        recipient_name=req.recipient_name,
        program_name=req.program_name,
        cert_type=req.cert_type,
        organizer=req.organizer,
        issue_date=req.issue_date,
        expiry_date=req.expiry_date,
        grade_or_score=req.grade_or_score,
    )
    return {
        "message": "Sertifikat berhasil diterbitkan.",
        "certificate": cert,
        "verification_url": f"{BASE_URL}/verify/{cert['cert_id']}",
        "pdf_download_url": (
            f"{BASE_URL}/api/v1/certificates/{cert['cert_id']}/pdf"
        ),
    }
  except Exception as e:
    raise HTTPException(status_code=400, detail=str(e))


@app.get(
    "/api/v1/certificates/{identifier}/pdf",
    tags=["Public API"],
    summary="Unduh File PDF Sertifikat Resmi",
)
def api_download_pdf(identifier: str):
  """Menghasilkan file PDF sertifikat resmi dengan QR Code verifikasi."""
  result = manager.verify_certificate(identifier)
  if not result["data"]:
    raise HTTPException(status_code=404, detail="Sertifikat tidak ditemukan.")

  cert_data = result["data"]
  verification_url = f"{BASE_URL}/verify/{cert_data['cert_id']}"
  pdf_bytes = manager.generate_pdf(cert_data, verification_url)

  filename = f"Sertifikat_{cert_data['cert_id']}.pdf"
  return Response(
      content=pdf_bytes,
      media_type="application/pdf",
      headers={"Content-Disposition": f'inline; filename="{filename}"'},
  )


@app.post(
    "/api/v1/certificates/{identifier}/revoke",
    tags=["Admin API"],
    summary="Cabut Sertifikat (Revocation)",
)
def api_revoke_certificate(identifier: str, req: RevokeRequest):
  success = manager.revoke_certificate(identifier, req.reason)
  if not success:
    raise HTTPException(
        status_code=404,
        detail="Sertifikat tidak ditemukan atau gagal dicabut.",
    )
  return {
      "message": f"Sertifikat {identifier} telah berhasil dicabut.",
      "reason": req.reason,
  }


# ==========================================
# 2. HALAMAN WEB VERIFIKASI (Untuk Pengguna HP & Browser)
# ==========================================


@app.get("/", response_class=HTMLResponse, tags=["Web Portal"])
def home_search_page():
  """Halaman portal pencarian verifikasi publik."""
  return """
    <!DOCTYPE html>
    <html lang="id">
    <head>
        <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Portal Verifikasi Sertifikat Resmi</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body class="bg-light d-flex align-items-center" style="min-height: 100vh;">
        <div class="container" style="max-width: 580px;">
            <div class="card shadow-sm border-0 p-4 rounded-4">
                <div class="text-center mb-4">
                    <h3 class="fw-bold text-primary">Portal Validasi Sertifikat</h3>
                    <p class="text-muted small">Layanan Verifikasi Keabsahan Dokumen Pelatihan & Sertifikasi</p>
                </div>
                <form action="/search" method="post">
                    <div class="mb-3">
                        <label class="form-label fw-semibold">Nomor Sertifikat atau ID Sistem</label>
                        <input type="text" name="query" class="form-control form-control-lg" placeholder="Contoh: CRT-8A7B6C5D4E" required>
                    </div>
                    <button type="submit" class="btn btn-primary btn-lg w-100 fw-semibold">Cek Keaslian Dokumen</button>
                </form>
            </div>
        </div>
    </body>
    </html>
    """


@app.post("/search", response_class=HTMLResponse, tags=["Web Portal"])
def handle_search(query: str = Form(...)):
  return verify_html_page(query)


@app.get(
    "/verify/{identifier}", response_class=HTMLResponse, tags=["Web Portal"]
)
def verify_html_page(identifier: str):
  """Halaman hasil verifikasi saat QR Code dipindai oleh kamera HP."""
  res = manager.verify_certificate(identifier)
  status = res["status"]
  data = res["data"]

  # Konfigurasi Badge & Warna Status
  if status == "VALID":
    badge = (
        '<span class="badge bg-success p-2 px-3 fs-6">✅ TERVERIFIKASI &'
        " RESMI</span>"
    )
    alert_class = "alert-success"
  elif status == "EXPIRED":
    badge = (
        '<span class="badge bg-warning text-dark p-2 px-3 fs-6">⚠️ SUDAH'
        " KEDALUWARSA</span>"
    )
    alert_class = "alert-warning"
  elif status == "REVOKED":
    badge = (
        '<span class="badge bg-danger p-2 px-3 fs-6">🚫 SERTIFIKAT'
        " DICABUT</span>"
    )
    alert_class = "alert-danger"
  elif status == "TAMPERED":
    badge = (
        '<span class="badge bg-danger p-2 px-3 fs-6">❌ INTEGRITAS DATA TIDAK'
        " VALID</span>"
    )
    alert_class = "alert-danger"
  else:
    badge = (
        '<span class="badge bg-secondary p-2 px-3 fs-6">❓ TIDAK'
        " DITEMUKAN</span>"
    )
    alert_class = "alert-secondary"

  detail_rows = ""
  if data:
    pdf_url = f"/api/v1/certificates/{data['cert_id']}/pdf"
    detail_rows = f"""
        <table class="table table-bordered mt-3">
            <tr><th class="bg-light" style="width: 38%;">Nama Penerima</th><td><strong class="fs-5">{data['recipient_name']}</strong></td></tr>
            <tr><th class="bg-light">Nama Program</th><td><strong>{data['program_name']}</strong></td></tr>
            <tr><th class="bg-light">Jenis Dokumen</th><td>{data['cert_type']}</td></tr>
            <tr><th class="bg-light">Penyelenggara</th><td>{data['organizer']}</td></tr>
            <tr><th class="bg-light">No. Registrasi</th><td><code>{data['cert_number']}</code></td></tr>
            <tr><th class="bg-light">ID Sistem</th><td><code>{data['cert_id']}</code></td></tr>
            <tr><th class="bg-light">Tanggal Terbit</th><td>{data['issue_date']}</td></tr>
            <tr><th class="bg-light">Masa Berlaku</th><td>{data['expiry_date'] or 'Seumur Hidup (Permanent)'}</td></tr>
            <tr><th class="bg-light">Predikat / Nilai</th><td>{data['grade_or_score'] or '-'}</td></tr>
        </table>
        <div class="mt-4 text-center">
            <a href="{pdf_url}" target="_blank" class="btn btn-outline-primary w-100 py-2 fw-semibold">📄 Unduh / Lihat Sertifikat Asli (PDF)</a>
        </div>
        """

  return f"""
    <!DOCTYPE html>
    <html lang="id">
    <head>
        <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Hasil Verifikasi Sertifikat</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body class="bg-light py-5">
        <div class="container" style="max-width: 680px;">
            <div class="card shadow-sm border-0 p-4 rounded-4">
                <div class="text-center mb-3">
                    {badge}
                    <h4 class="mt-3 fw-bold">Hasil Pemeriksaan Sertifikat</h4>
                </div>
                <div class="alert {alert_class} text-center py-2 mb-3">
                    {res['message']}
                </div>
                {detail_rows}
                <div class="text-center mt-4 border-top pt-3">
                    <a href="/" class="text-decoration-none text-muted small">← Kembali ke Form Pencarian</a>
                </div>
            </div>
        </div>
    </body>
    </html>
    """