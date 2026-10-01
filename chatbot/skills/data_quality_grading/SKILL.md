# DATA QUALITY GRADING SKILL

## Purpose
This skill defines classification rules and completeness thresholds for data quality grades (Grade A to Grade F) applied to uploaded datasets.

## 1. Six Core Identity Elements
Identity completeness is evaluated across six individual data fields:
1. National ID Number (NIK) - 16 valid digits
2. Full Name (Nama Lengkap)
3. Place of Birth (Tempat Lahir)
4. Date of Birth (Tanggal Lahir)
5. Gender (Jenis Kelamin)
6. Mother's Name (Nama Ibu Kandung)

## 2. Quality Grade Classification Rules

### Grade A (Sangat Lengkap / Very Complete)
- All 6 core data elements fully filled and strictly validated.
- NIK must be exactly 16 valid digits.
- Full Name, Place of Birth, Date of Birth, Gender, and Mother's Name 100% complete.
- High consistency and zero validation errors across all fields.

### Grade B (Hampir Lengkap / Almost Complete)
- Full Name: 100% complete.
- NIK: At least 70% complete/correct.
- Place of Birth, Date of Birth, and Gender: Each at least 70% complete.
- Mother's Name: At least 60% complete.
- Minor gaps or minor field inconsistencies present.

### Grade C (Cukup Lengkap / Fairly Complete)
- Five core identity fields present (Full Name, Place of Birth, Date of Birth, Gender, Mother's Name).
- NIK is not required for Grade C classification.
- Core identity fields are filled, even if not fully verified against master registry.

### Grade D (Kurang Lengkap dengan Persyaratan Minimum / Less Complete with Minimum Requirement)
- Five core identity elements present with minimum completeness threshold:
  - Full Name: 100% complete.
  - Place of Birth, Date of Birth, Gender: Each at least 70% complete.
  - Mother's Name: At least 60% complete.
- **Mengapa ada data Grade D?**: Terjadi ketika dataset memiliki kelengkapan minimum pada atribut biodata dasar (Nama, Tempat Lahir, Tanggal Lahir, Jenis Kelamin, Nama Ibu), **tetapi field NIK kosong, formatnya salah (< 16 digit), atau tidak memenuhi ambang batas validasi NIK**. Data ini tetap dapat diproses pemadanan berbasis nama dan tanggal lahir, namun memiliki tingkat kepastian lebih rendah sehingga memerlukan peninjauan lebih lanjut.

### Grade E (Sangat Tidak Lengkap / Very Incomplete)
- Minimum of 3 data elements available in flexible combinations (e.g. Nama + Tanggal Lahir + Jenis Kelamin).
- Highly variable completeness, non-standard formats.

### Grade F (Custom / User-Defined Mapping)
- Fallback grade assigned when column headers are non-standard and cannot be automatically parsed into the 6 core identity fields. Requires manual column mapping by the user.
