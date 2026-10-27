Q: Apa peran Synchrono AI Assistant?

Jawaban: Synchrono AI Assistant berperan sebagai asisten analisis dan penjelasan. AI dapat menjelaskan alasan data tidak padan dengan bahasa sederhana, merekomendasikan penanganan anomali berdasarkan pola dan referensi data, menjawab pertanyaan tentang fitur dan status dengan menggunakan data sistem, serta merangkum statistik, tren, dan daftar kasus per Kementerian/Lembaga (K/L).

<!-- page break -->

Q: Apa yang dilakukan AI ketika menjelaskan alasan data tidak padan?

Jawaban: AI mengambil alasan diskrepansi yang tercatat untuk kasus yang ditinjau, membandingkan elemen data yang relevan, lalu menjelaskan perbedaannya dengan bahasa sederhana. Contohnya dapat berupa variasi ejaan atau perbedaan tanggal lahir. Penjelasan harus mengikuti bukti yang tersedia dan tidak mengarang alasan yang tidak tercatat.

<!-- page break -->

Q: Bagaimana AI merekomendasikan penanganan anomali?

Jawaban: AI menggunakan pola anomali dan aturan atau referensi data yang tersedia untuk menyarankan langkah pemeriksaan bagi operator. Rekomendasi AI merupakan bahan pertimbangan; bukan perubahan data atau keputusan akhir.

<!-- page break -->

Q: Apa saja enam elemen identitas untuk penilaian kelengkapan grading?

Jawaban: Enam elemen yang dinilai adalah NIK (16 digit valid), nama lengkap, tempat lahir, tanggal lahir, jenis kelamin, dan nama ibu kandung.

<!-- page break -->

Q: Apa kriteria umum Grade A?

Jawaban: Grade A menunjukkan keenam elemen identitas terisi penuh dan tervalidasi ketat. NIK harus tepat 16 digit valid; nama lengkap, tempat lahir, tanggal lahir, jenis kelamin, dan nama ibu kandung lengkap 100%, dengan konsistensi tinggi dan tanpa kesalahan validasi.

<!-- page break -->

Q: Apa kriteria umum Grade B?

Jawaban: Grade B menunjukkan data hampir lengkap: nama lengkap 100%; NIK setidaknya 70% lengkap atau benar; tempat lahir, tanggal lahir, dan jenis kelamin masing-masing setidaknya 70%; serta nama ibu kandung setidaknya 60%. Masih dapat ada kekurangan atau inkonsistensi ringan.

<!-- page break -->

Q: Apa kriteria umum Grade C?

Jawaban: Grade C berarti lima elemen biodata dasar—nama lengkap, tempat lahir, tanggal lahir, jenis kelamin, dan nama ibu kandung—tersedia. NIK tidak menjadi syarat klasifikasi Grade C; elemen biodata tersebut belum tentu seluruhnya tervalidasi terhadap master registry.

<!-- page break -->

Q: Apa arti Grade D dan mengapa data bisa mendapat Grade D?

Jawaban: Grade D berarti data kurang lengkap tetapi masih memenuhi ambang minimum biodata dasar: nama lengkap 100%; tempat lahir, tanggal lahir, dan jenis kelamin masing-masing minimal 70%; nama ibu kandung minimal 60%. Pada umumnya, NIK kosong, kurang dari 16 digit, atau tidak memenuhi validasi. Grade adalah penilaian kualitas data, bukan keputusan akhir status padan.

<!-- page break -->

Q: Apa kriteria umum Grade E?

Jawaban: Grade E menunjukkan data sangat tidak lengkap, dengan sedikitnya tiga elemen identitas tersedia dalam kombinasi yang fleksibel. Kelengkapan dapat sangat bervariasi dan format data bisa tidak standar.

<!-- page break -->

Q: Kapan Grade F digunakan?

Jawaban: Grade F adalah grade fallback untuk pemetaan kustom. Grade ini digunakan ketika header kolom tidak standar dan tidak dapat dipetakan otomatis ke enam elemen identitas inti; pemetaan kolom manual oleh pengguna diperlukan.

<!-- page break -->

Q: Apa arti AUTO_MATCH dan AUTO_UNMATCH?

Jawaban: AUTO_MATCH berarti sistem otomatis mencocokkan identitas dengan master registry. AUTO_UNMATCH berarti sistem tidak menemukan kandidat yang cukup meyakinkan. AI dapat menjelaskan alasan berdasarkan bukti, tetapi tidak mengubah status.

<!-- page break -->

Q: Apa arti MANUAL_REVIEW, MANUAL_MATCH, dan MANUAL_UNMATCH?

Jawaban: MANUAL_REVIEW berarti kasus ditandai untuk pertimbangan manusia karena confidence berada di batas atau ada perbedaan elemen data. MANUAL_MATCH berarti operator mengonfirmasi kecocokan; MANUAL_UNMATCH berarti operator mengonfirmasi bahwa data tidak cocok.

<!-- page break -->

Q: Apakah AI boleh menentukan atau mengubah status padan?

Jawaban: Tidak. AI hanya menjelaskan dan memberikan rekomendasi. Penentuan atau perubahan status padan merupakan tanggung jawab aturan platform dan operator.

<!-- page break -->

Q: Apakah AI memproses setiap baris data?

Jawaban: Tidak. Pemrosesan setiap baris dijalankan oleh aturan dan pipeline platform, bukan reasoning LLM. LLM reasoning dipanggil hanya untuk kasus yang ditinjau.

<!-- page break -->

Q: Apakah AI mengirim data ke luar data center Dukcapil?

Jawaban: AI tidak boleh mengirim atau mengekspor data ke luar lingkungan platform yang diizinkan. Batas deployment dan pemrosesan mengikuti konfigurasi lingkungan platform.

<!-- page break -->

Q: Bagaimana aturan tautan preview dan investigasi?

Jawaban: Setelah matching dan reasoning sama-sama berstatus SUCCESS, Grade A menggunakan preview link; grade selain A menggunakan investigation link. Tautan harus diambil persis dari nilai yang tersimpan di sistem, bukan dibuat atau ditebak oleh AI. Jika proses masih berlangsung atau tautan bernilai kosong, chatbot menyampaikan bahwa tautan belum tersedia.

<!-- page break -->

Q: Apakah FAQ memberikan status terkini untuk batch atau kasus tertentu?

Jawaban: Tidak. FAQ berisi penjelasan dan aturan yang relatif stabil. Status dan progres batch atau kasus dapat berubah, sehingga chatbot harus memeriksanya dari StarRocks setiap kali diperlukan; jawaban status dinamis tidak boleh diambil dari cache FAQ.
