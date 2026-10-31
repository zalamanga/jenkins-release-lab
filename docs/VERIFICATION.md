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

**PASS pada 31 Oktober 2026.** Source lab yang diuji adalah [`67f4557b0adb7a0157b0fb8a1ae5565cd16ade9a`](https://github.com/zalamanga/jenkins-release-lab/tree/67f4557b0adb7a0157b0fb8a1ae5565cd16ade9a); source aplikasi tetap `e3547e69851165fa7b20154502aa05ad8d3481cd`. [Run CI yang berhasil](https://github.com/zalamanga/jenkins-release-lab/actions/runs/41211924065) menjalankan Jenkins 2.580.2 sungguhan. Windows Docker Desktop menjalankan source lab yang sama.

| Pemeriksaan | Hasil yang direkam |
|---|---|
| Release engine/control client | 34 tes Python lulus; termasuk startup timeout, redirect autentikasi dan pergantian generasi worker Nginx |
| Source/plugin | 71 checksum SHA256 plugin dipenuhi pada build image controller |
| Go dan PostgreSQL | Delapan kasus lulus, nol failure dan nol skip pada masing-masing empat build deployment; tujuh integrasi DB dan satu unit |
| Lima build CI | #1 SUCCESS, #2 SUCCESS, #3 FAILURE, #4 SUCCESS, #5 FAILURE; seluruhnya sesuai skenario |
| Lima build Windows | #5 SUCCESS, #6 SUCCESS, #7 FAILURE, #8 SUCCESS, #9 FAILURE; seluruhnya sesuai skenario |
| HTTP smoke | 12 request untuk setiap probe yang lulus; rollback tidak mengulang tes Go |
| Fault sesudah cutover | HTTP 504 di CI dan HTTP 504 di Windows; recovery menjalankan 12 request dan lulus |
| State dan image | Kandidat ditolak mempertahankan active state; rollback membuat ulang image ID awal; recovery mempertahankan byte state committed |
| Data | Produk sentinel stok 17 tetap 17 pada seluruh lima build di kedua lingkungan |
| UI | Login, lima record build, JUnit, console penolakan, artifact rollback dan form parameter lulus di Chromium CI serta Microsoft Edge Windows; nol page error |

Keluaran permanen tersedia pada [laporan CI](evidence/ci-verification.json), [laporan Windows](evidence/windows-verification.json), [pemeriksaan UI CI](evidence/ui-checks.json), [pemeriksaan UI Windows](evidence/windows-ui-checks.json), serta [manifest screenshot](evidence/manifest.json). Empat gambar yang ditampilkan README berasal dari run CI tersebut dan tidak diubah.

Respons 502 dan 504 sama-sama merupakan kegagalan upstream yang diterima oleh skenario fault; laporan menyimpan status yang benar-benar diamati. Pada dua pelaksanaan di atas statusnya 504. Verifier tetap mewajibkan fault sesudah cutover, recovery yang lulus, image awal yang tepat, state yang sama, serta sentinel utuh.

Build Windows #1–#4 adalah percobaan integrasi awal yang gagal dan tidak dihitung sebagai rangkaian lulus. Bukti Windows mencatat hanya rangkaian final #5–#9. Riwayat controller dipertahankan. Setelah pengujian dan capture, container lab serta Docker Desktop dihentikan; volume data tetap ada. Durasi build mencakup unduhan dan cache, sehingga tidak digunakan sebagai benchmark.

## Cara menilai bukti

Hasil `SUCCESS` tanpa JUnit dan artifact yang sesuai belum cukup. Cocokkan nomor build dengan laporan, cocokkan source aplikasi dengan commit yang dipatok, lalu periksa active image ID sebelum dan sesudah skenario gagal. `state_sha256` pada proof berasal dari byte file state yang tersimpan. Hash yang sama sebelum dan sesudah penolakan kandidat atau recovery membuktikan bahwa engine tidak mengubah state committed pada percobaan gagal. Pada manual rollback, periksa pula bahwa container release previous telah diganti sebelum engine membuat ulang image tersebut.

Screenshot harus menampilkan UI klasik Jenkins yang sebenarnya. Gambar buatan atau dashboard khusus tidak menggantikan build history, halaman test result, maupun artifact Jenkins.

## Batas hasil

Tes ini memakai data sintetis pada lingkungan lokal atau runner CI. Hasilnya membuktikan perilaku skenario yang dijalankan pada identitas source yang dicatat. Tes tidak mengukur SLA, kapasitas, ketersediaan produksi, keamanan produksi, atau kompatibilitas migrasi skema baru.
