"""Deterministic intent gates for FAQ-only direct answers vs live-data questions."""

import re


_FAQ_RULE_PATTERNS = (
    r"\b(?:apa saja yang dilakukan|apa yang dilakukan|peran|fungsi|fitur|tugas utama)\b.{0,35}\b(?:ai|chatbot|synchrono)\b",
    r"\b(?:apa yang tidak dilakukan|apa yang bukan tugas|batas)\b.{0,35}\b(?:ai|chatbot|synchrono)\b",
    r"\b(?:ai|chatbot)\b.{0,50}\b(?:mengubah|menentukan|memproses setiap baris|mengirim data|menjelaskan|merekomendasikan)\b",
    r"\b(?:aturan|kriteria|definisi|arti|grade)\b.{0,30}\b(?:grade\s*[a-f]|[a-f])\b",
    r"\b(?:apa arti|arti|definisi|kriteria)\b.{0,25}\bgrade\s*[a-f]\b",
    r"\b(?:apa arti|apa itu|jelaskan arti|definisi|aturan|kriteria)\b.{0,50}\b(?:grade\s*[a-f]|auto_match|auto_unmatch|manual_review|manual_match|manual_unmatch|status padan)\b",
    r"\b(?:kenapa|mengapa)\s+grade\s*[a-f]\b",
    r"\bapa arti\b.{0,30}\b(?:grade|status|mismatch)\b",
)

_LIVE_DATA_PATTERNS = (
    r"\b(?:berapa|jumlah|total|tampilkan|tunjukkan|cari|cek|lihat|daftar|rekap|ringkas|statistik|tren|trend|peringkat|top\s+\d+)\b.{0,45}\b(?:batch|berkas|file|dataset|status|progres|progress|record|kasus|data terkini|unggahan|institusi|k/l)\b",
    r"\b(?:batch|berkas|file|dataset|status|progres|progress|record|kasus|unggahan|institusi|k/l)\b.{0,45}\b(?:berapa|jumlah|total|tampilkan|tunjukkan|cari|cek|lihat|daftar|rekap|ringkas|statistik|tren|trend|terbanyak|terakhir)\b",
    r"\b(?:hari|minggu|bulan|tahun)\s+(?:terakhir|ini|lalu)\b",
    r"\b(?:batch|dataset|institusi|k/l)\b",
    r"\b(?:peserta|orang bernama|nama budi|nama \w+|nik|id_incoming|file_id)\b",
    r"\b(?:status|progres|progress)\b.{0,50}\b(?:sekarang|terkini|batch|berkas|file|unggah|sinkron|pemadanan|matching|grading)\b",
    r"\b(?:sekarang|terkini|saat ini)\b.{0,35}\b(?:status|progres|progress|batch|berkas|file)\b",
    r"\b[a-f0-9]{8}\b",
    r"\b\d{4,}\b",
    r"\.(?:csv|xlsx|xls|parquet|json)\b",
    r"\b(?:tadi|sebelumnya|tersebut|dari daftar|daftar tadi|yang tadi)\b",
    r"\b(?:tabel|table|kolom|column|database|db|skema|schema|syncrono_\w+)\b",
)

_PUBLIC_SERVICE_PATTERNS = (
    r"\b(?:syarat|prosedur|cara|mengurus|membuat|penerbitan|aktivasi)\b.{0,50}\b(?:ktp(?:-el)?|kartu keluarga|\bkk\b|kia|ikd|akta|dukcapil)\b",
    r"\b(?:ktp(?:-el)?|kartu keluarga|\bkk\b|kia|ikd|akta|dukcapil)\b.{0,50}\b(?:syarat|prosedur|cara|mengurus|membuat|penerbitan|aktivasi)\b",
)

_DOCUMENT_TOPIC_PATTERNS = (
    r"\b(?:dokumen|document|sop|pdf|panduan|pedoman|manual|kebijakan|materi|referensi)\b",
    r"\b(?:knowledge\s*base|basis pengetahuan)\b",
)

_DOCUMENT_SUMMARY_PATTERNS = (
    r"\b(?:ringkas(?:an)?|rangkum(?:an)?|ikhtisar|summary)\b.{0,50}\b(?:dokumen|document|file|berkas|sop|pdf|panduan|pedoman|manual|kebijakan|materi|referensi)\b",
    r"\b(?:dokumen|document|file|berkas|sop|pdf|panduan|pedoman|manual|kebijakan|materi|referensi)\b.{0,50}\b(?:ringkas(?:an)?|rangkum(?:an)?|ikhtisar|summary)\b",
    r"\b(?:apa|apakah)\s+(?:isi|konten)\b.{0,50}\b(?:dokumen|document|file|berkas|sop|pdf|panduan|pedoman|manual|kebijakan|materi|referensi)\b",
    r"\b(?:jelaskan|sebutkan|tampilkan)\b.{0,25}\b(?:isi|konten)\b.{0,35}\b(?:dokumen|document|file|berkas|sop|pdf|panduan|pedoman|manual|kebijakan|materi|referensi)\b",
)

_DOCUMENT_CONTENT_PATTERNS = (
    r"\b(?:isi|konten|ringkas(?:an)?|rangkum(?:an)?|jelaskan|sebutkan|apa saja)\b.{0,60}\b(?:dokumen|document|sop|pdf|panduan|pedoman|manual|kebijakan|materi|referensi)\b",
    r"\b(?:dokumen|document|sop|pdf|panduan|pedoman|manual|kebijakan|materi|referensi)\b.{0,60}\b(?:isi|konten|ringkas(?:an)?|rangkum(?:an)?|jelaskan|sebutkan|apa saja)\b",
    r"\b(?:isi|konten|ringkas(?:an)?|rangkum(?:an)?|jelaskan)\b.{0,40}\b(?:file|berkas)\b.{0,40}\b(?:unggah|upload|terbaru|tersebut|ini)\b",
    r"\b(?:file|berkas)\b.{0,40}\b(?:unggah|upload)\b.{0,40}\b(?:isi|konten|ringkas(?:an)?|rangkum(?:an)?|jelaskan|apa saja)\b",
    r"\b(?:menurut|berdasarkan|dalam)\b.{0,30}\b(?:dokumen|document|sop|pdf|panduan|pedoman|manual|kebijakan|materi|referensi)\b",
)


def is_live_data_question(question: str) -> bool:
    text = question.casefold()
    return any(re.search(pattern, text) for pattern in _LIVE_DATA_PATTERNS)


def is_platform_faq_question(question: str) -> bool:
    """True only for stable platform explanations suitable for direct FAQ answers."""
    text = question.casefold()
    if is_live_data_question(text):
        return False
    return any(re.search(pattern, text) for pattern in _FAQ_RULE_PATTERNS)


def is_out_of_scope_public_service_question(question: str) -> bool:
    text = question.casefold()
    return any(re.search(pattern, text) for pattern in _PUBLIC_SERVICE_PATTERNS)


def is_document_question(question: str) -> bool:
    """True when the question refers to a general uploaded document/source."""
    text = question.casefold()
    return any(re.search(pattern, text) for pattern in _DOCUMENT_TOPIC_PATTERNS)


def is_document_content_question(question: str) -> bool:
    """True when the user asks for content grounded in general documents."""
    text = question.casefold()
    return any(re.search(pattern, text) for pattern in _DOCUMENT_CONTENT_PATTERNS)


def is_document_summary_question(question: str) -> bool:
    """True when the user asks for a broad summary of an uploaded document."""
    text = question.casefold()
    return any(re.search(pattern, text) for pattern in _DOCUMENT_SUMMARY_PATTERNS)
