from src.knowledge.question_routing import (
    is_document_content_question,
    is_document_question,
    is_document_summary_question,
    is_live_data_question,
    is_out_of_scope_public_service_question,
    is_platform_faq_question,
)


def test_stable_ai_role_question_is_platform_faq():
    assert is_platform_faq_question("Apa peran AI Synchrono?")
    assert not is_live_data_question("Apa peran AI Synchrono?")


def test_grade_definition_is_platform_faq_but_grade_distribution_is_live_data():
    assert is_platform_faq_question("Apa arti Grade D?")
    assert is_platform_faq_question("Apa arti Grade D dan faktor data apa yang bisa menyebabkannya?")
    assert is_live_data_question("Tampilkan jumlah batch per Grade A sampai F")
    assert not is_platform_faq_question("Tampilkan jumlah batch per Grade A sampai F")


def test_relative_time_and_batch_status_are_live_data():
    assert is_live_data_question("Berapa batch 30 hari terakhir?")
    assert is_live_data_question("Apa status batch fav-001 sekarang?")
    assert not is_platform_faq_question("Apa status batch fav-001 sekarang?")


def test_public_service_ktp_procedure_is_out_of_scope():
    q = "Apa syarat KTP-el baru setelah berusia 17 tahun?"
    assert is_out_of_scope_public_service_question(q)
    assert not is_platform_faq_question(q)


def test_document_questions_are_detected():
    assert is_document_question("Cari dokumen SOP terbaru")
    assert is_document_content_question("Jelaskan isi dokumen SOP terbaru")
    assert is_document_content_question("Ringkas panduan onboarding")
    assert is_document_content_question("Apa isi file yang saya upload?")
    assert not is_document_content_question("Berapa jumlah file untuk Fav Institute?")


def test_uploaded_file_content_question_is_not_live_data():
    q = "Apa isi file yang saya upload?"
    assert not is_live_data_question(q)
    assert is_live_data_question("Berapa jumlah file untuk Fav Institute?")


def test_document_summary_questions_are_detected():
    assert is_document_summary_question("Apa isi file yang saya upload?")
    assert is_document_summary_question("Ringkas dokumen SOP terbaru")
    assert is_document_summary_question("Jelaskan isi file yang saya upload")
    assert not is_document_summary_question("Berapa denda keterlambatan dalam dokumen SOP?")


def test_table_and_database_references_are_live_data():
    q = "Apa rentang skor kualitas, label keparahan (severity), dan status can_proceed untuk Grade C di tabel syncrono_service_grade_bands?"
    assert is_live_data_question(q)
    assert not is_platform_faq_question(q)

