# DATA QUALITY GRADING SKILL

## Purpose
This skill defines the active data-quality grade model used in `syncrono_starrocks_v002`.

## 1. Six Core Identity Elements
1. National ID Number (NIK)
2. Full Name (Nama Lengkap)
3. Place of Birth (Tempat Lahir)
4. Date of Birth (Tanggal Lahir)
5. Gender (Jenis Kelamin)
6. Mother's Name (Nama Ibu Kandung)

## 2. Grade Bands
Read `syncrono_service_grade_bands` for the authoritative values:
- A: score 90–100, “Sangat Baik”, can proceed.
- B: score 70–89, “Baik”, can proceed.
- C: score 50–69, “Cukup”, can proceed.
- D: score 30–49, “Kurang”, can proceed.
- E: score 10–29, “Sangat Kurang”, can proceed.
- F: score 0–9, “Kritis”, cannot proceed.

The score and letter for a completed job are stored in `syncrono_service_grading_results.grade_letter` and `quality_score`; use `phase = grading_phase` for the final result.

## 3. Completeness Criteria
Read `syncrono_service_grade_criteria` for authoritative thresholds. Current configuration:
- **Grade A (`grade_id=1`)**: NIK required; all six elements at 100%; trusted NIK required.
- **Grade B (`grade_id=2`)**: NIK required; Full Name 100%; Place of Birth, Date of Birth, and Gender >= 70%; Mother's Name >= 60%; trusted NIK >= 70%.
- **Grade C (`grade_id=3`)**: NIK forbidden; Full Name, Place of Birth, Date of Birth, Gender, and Mother's Name at 100%.
- **Grade D (`grade_id=4`)**: NIK forbidden; Full Name 100%; Place of Birth, Date of Birth, and Gender >= 70%; Mother's Name >= 60%.
- Grades E and F are assigned by the score bands; no separate completeness row is defined in the current criteria table.

## 4. Interpretation
- Grade D means the minimum biodata completeness is present, but NIK is absent/invalid, so matching certainty is lower.
- Grade F means a critical score/quality level and `can_proceed = 0`.
- Always distinguish “NIK kosong/tidak valid” from “NIK ada tetapi tidak cocok” when explaining results.
- Use `syncrono_service_grading_results.summary` for completeness/anomaly counts, and `syncrono_kl_records.is_anomaly` / `anomaly_type` for row-level evidence.
