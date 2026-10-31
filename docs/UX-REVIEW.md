# Tinjauan UX dan delivery gate

**PASS, 31 Oktober 2026.** Lingkupnya adalah README dan panduan lab, alur desktop Jenkins yang dipakai saat demo, serta satu entri tambahan pada katalog portfolio yang sudah ada. Source kode yang diuji adalah `67f4557b0adb7a0157b0fb8a1ae5565cd16ade9a`. UI klasik Jenkins dipertahankan; tidak ada dashboard khusus atau desain ulang portfolio.

## Hard Gate: PASS

Angka berasal dari [bukti CI](evidence/ci-verification.json), [bukti Windows](evidence/windows-verification.json), dan [run CI yang lulus](https://github.com/zalamanga/jenkins-release-lab/actions/runs/41211924065). Tidak ada statistik pelanggan, testimonial atau klaim kapasitas produksi. Guard memeriksa laporan sebelum upload, dan pemeriksaan lokal mencakup source, README, lock, kredensial serta secret node yang diketahui. Direktori privat tidak dilacak Git. Empat PNG diperiksa langsung: tidak ada form login terisi atau kredensial yang terlihat. Hash dan ukuran gambar dicatat pada [manifest](evidence/manifest.json).

## Purpose-Gate: PASS

Job history menunjukkan urutan rilis; halaman JUnit menunjukkan delapan kasus nyata; console menunjukkan penolakan kandidat; artifact rollback menunjukkan image ID awal yang dipulihkan. Keempat gambar berasal dari Jenkins pada runner CI. Preview katalog memakai job history dengan label `Jenkins screenshot`. Tidak ada logo, avatar, dekorasi atau struktur navigasi baru yang dibuat untuk lab ini.

## Liveliness: PASS

Arah yang dipakai adalah UI klasik Jenkins bagi developer, dial **ENERGY 1 / RHYTHM 1 / MOTION 1**. Stage View menjadi fokus untuk membandingkan build. Kolom stage, warna status, nama aksi, JUnit dan artifact memberi identitas proyek dari pekerjaan rilis yang nyata. Entri portfolio mengikuti komposisi dan gaya yang sudah ada. Judul, stack, deskripsi dan screenshot menjelaskan isi lab tanpa menambah gerakan atau hiasan.

## Craftsmanship dan Quality Locks: PASS

[Pemeriksaan UI CI](evidence/ui-checks.json) dan [pemeriksaan UI Windows](evidence/windows-ui-checks.json) mencatat login, lima record build, JUnit, console penolakan, artifact rollback dan form parameter yang dibuka tanpa build tambahan. Kedua lingkungan menghasilkan empat capture pada viewport 1440 x 1100 dan nol page error.

[Ringkasan pemeriksaan portfolio](evidence/portfolio-review.json) mencatat katalog 99 proyek dengan 98 entri lama beserta urutannya tetap. Pencarian, filter kategori yang sesuai/tidak sesuai, tautan commit source, gambar penuh dan reset lulus. Gambar termuat serta tidak ada overflow horizontal pada lebar 320, 390 dan 1440 px. Preview menggunakan PNG yang sama dengan screenshot job history; hash-nya cocok. Referensi source final dapat diperiksa pada [katalog portfolio publik](https://zalamanga.github.io/assets/data/projects.json).

Pemeriksaan ini mencakup alur Jenkins desktop yang disebutkan dan penambahan konten katalog. Ini tidak mengesahkan seluruh UI vendor, tampilan mobile Jenkins, atau kepatuhan WCAG menyeluruh. Tidak ada perubahan kontras, tipografi, navigasi atau theme vendor yang diterbitkan oleh proyek ini.
