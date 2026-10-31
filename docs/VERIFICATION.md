# Catatan verifikasi

Dokumen ini memisahkan prosedur yang harus dijalankan dari hasil yang telah direkam. Kehadiran source tes, Jenkinsfile, atau workflow tidak dianggap sebagai bukti bahwa tes sudah lulus.

## Identitas yang diperiksa

Source aplikasi adalah ReserveFlow commit `e3547e69851165fa7b20154502aa05ad8d3481cd`. Setiap build harus merekam source aplikasi tersebut, source lab yang dipakai, nomor build Jenkins, release ID, dan image ID bila menghasilkan image. Release ID baru dari source yang sama tidak dihitung sebagai commit fitur baru.

## Rangkaian verifikasi runtime

| Urutan | Aksi | Hasil Jenkins yang diwajibkan | Pemeriksaan tambahan |
|---|---|---|---|
| 1 | `DEPLOY_GOOD` | `SUCCESS` | Release sehat pertama aktif; tes aplikasi dan HTTP smoke ada |
| 2 | `DEPLOY_GOOD` | `SUCCESS` | Release ID baru aktif dari source aplikasi yang sama; previous release tercatat |
| 3 | `DEPLOY_UNHEALTHY` | `FAILURE` | Health gate menolak kandidat; active release tidak berubah |
| 4 | `ROLLBACK` | `SUCCESS` | Previous image ID aktif kembali setelah container release sebelumnya ditimpa kandidat gagal |
| 5 | `DEPLOY_POSTCHECK_FAIL` | `FAILURE` | Cutover terjadi, post-check gagal, lalu engine memulihkan release sehat sebelumnya |

Verifier juga menulis sentinel sintetis pada PostgreSQL deployment dan memeriksanya selama rangkaian tersebut. Database lab harus tetap sama. Verifier memeriksa artifact dan status dari API Jenkins, bukan menyimpulkan hasil pipeline dari exit code Docker Compose.

## Lapisan pemeriksaan

| Lapisan | Bukti yang dicari |
|---|---|
| Release engine Python | Hasil `unittest` untuk state, health gate, image ID, pemulihan, dan batas laporan |
| Aplikasi Go | Delapan tes Go dengan PostgreSQL tersedia: tujuh tes integrasi database dan satu tes unit; JUnit menolak skip atau tes wajib yang hilang |
| Deployment HTTP | Dua belas request smoke yang memeriksa perilaku API melalui gateway |
| Jenkins | Controller 0 executor, agent 1 executor, SCM pipeline, stage, parameter, hasil build, JUnit dan artifact |
| Data | Sentinel sintetis bertahan saat slot berganti dan recovery berjalan |
| Publikasi | Hanya laporan publik dan screenshot yang dipilih; secret serta controller home tidak diunggah |

Delapan tes aplikasi berasal dari source ReserveFlow yang dipatok: `TestCursorAndExpiryBoundary`, `TestLastUnitConcurrentRequests`, `TestConcurrentIdempotencyAndCanonicalReplay`, `TestAtomicRollbackAndRetry`, `TestExpiredHoldDoesNotBlockOrConfirm`, `TestCancellationReleaseAndConfirmationReplay`, `TestConfirmCancelRaceOneTransition`, dan `TestTenantIsolationPaginationAndValidation`. `TestCursorAndExpiryBoundary` adalah tes unit murni; tujuh tes lain memakai fixture PostgreSQL nyata.

## Hasil pelaksanaan

Hasil runtime belum dicatat pada draft awal ini. Bagian ini akan diisi dari laporan yang dihasilkan verifier setelah Jenkins dan agent menjalankan rangkaian di atas. Sampai bukti tersebut tersedia, tabel skenario merupakan syarat verifikasi, bukan klaim keberhasilan.

## Cara menilai bukti

Hasil `SUCCESS` tanpa JUnit dan artifact yang sesuai belum cukup. Cocokkan nomor build dengan laporan, cocokkan source aplikasi dengan commit yang dipatok, lalu periksa active image ID sebelum dan sesudah skenario gagal. `state_sha256` pada proof berasal dari byte file state yang tersimpan. Hash yang sama sebelum dan sesudah penolakan kandidat atau recovery membuktikan bahwa engine tidak mengubah state committed pada percobaan gagal. Pada manual rollback, periksa pula bahwa container release previous telah diganti sebelum engine membuat ulang image tersebut.

Screenshot harus menampilkan UI klasik Jenkins yang sebenarnya. Gambar buatan atau dashboard khusus tidak menggantikan build history, halaman test result, maupun artifact Jenkins.

## Batas hasil

Tes ini memakai data sintetis pada lingkungan lokal atau runner CI. Hasilnya membuktikan perilaku skenario yang dijalankan pada identitas source yang dicatat. Tes tidak mengukur SLA, kapasitas, ketersediaan produksi, keamanan produksi, atau kompatibilitas migrasi skema baru.
