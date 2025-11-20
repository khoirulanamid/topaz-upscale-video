# Topaz Video Upscaler - Adobe Stock Professional Edition

> A lightweight GUI wrapper to prepare and upload short videos to Topaz Labs' video API
> and re-encode outputs to meet Adobe Stock requirements.

## Ringkasan
- File utama: `topaz_video_gui_pro.py`
- UI: Tkinter (Dark theme)
- Fungsi utama: memilih video, membuat request ke API Topaz, mengunggah, menunggu proses,
  lalu mengunduh dan melakukan re-encode `ffmpeg` agar sesuai spesifikasi Adobe Stock.

## Prasyarat (yang harus diinstal)
- Windows 10/11
- Python 3.8+ (disarankan 3.8 — 3.11)
- FFmpeg (full build) dan FFprobe — tambahkan folder `bin` FFmpeg ke `PATH`.
- Paket Python: `opencv-python`, `requests`

## Cara install Python (Windows) — langkah cepat
1. Download installer dari https://www.python.org/downloads/windows/ (pilih versi 3.8+).
2. Jalankan installer → centang opsi "Add Python 3.x to PATH" lalu pilih "Install Now".
   - Pastikan opsi Tcl/Tk (untuk Tkinter) tercentang — biasanya sudah aktif pada installer resmi.
3. Verifikasi instalasi di PowerShell:

```powershell
py --version
python --version
```

Jika perintah di atas menampilkan versi Python, instalasi berhasil.

Jika Anda ingin lingkungan terisolasi (direkomendasikan):

```powershell
py -m venv .venv
.\.venv\Scripts\Activate
```

## Cara install FFmpeg (Windows)
1. Unduh build statis FFmpeg dari salah satu sumber terpercaya:
   - https://www.gyan.dev/ffmpeg/builds/
   - https://www.ffmpeg.org/download.html (link ke builds pihak ketiga untuk Windows)
2. Ekstrak hasil download ke folder, contoh: `C:\tools\ffmpeg` sehingga `ffmpeg.exe` berada di `C:\tools\ffmpeg\bin`.
3. Tambahkan folder `bin` ke `PATH` (cepat via PowerShell — ini menambahkan ke PATH user):

```powershell
$newPath = "$env:PATH;C:\tools\ffmpeg\bin"
[Environment]::SetEnvironmentVariable("Path", $newPath, "User")
```

4. Tutup terminal lalu buka kembali (atau buka terminal baru) lalu verifikasi:

```powershell
ffmpeg -version
ffprobe -version
```

Jika versi tampil, FFmpeg sudah tersedia di PATH.

Catatan: Jika tidak nyaman mengubah PATH via command line, tambahkan `C:\tools\ffmpeg\bin` melalui
Settings → System → About → Advanced system settings → Environment Variables → Path → Edit.

## Menginstall dependensi Python

Jika menggunakan virtualenv aktif (direkomendasikan):

```powershell
py -m pip install --upgrade pip
py -m pip install opencv-python requests
```

Catatan:
- `tkinter` biasanya disertakan bersama installer Python dari python.org. Jika aplikasi gagal import `tkinter`,
  jalankan installer Python lagi dan pastikan opsi Tcl/Tk dipilih.

## Jalankan aplikasi

1. Pastikan virtualenv aktif (jika dibuat):

```powershell
.\.venv\Scripts\Activate
```

2. Jalankan aplikasi GUI:

```powershell
py .\topaz_video_gui_pro.py
```

3. Di UI aplikasi:
- Pilih file `API Keys` (plain text, satu kunci per baris). Contoh `api_keys.txt`:

```
KEY1_EXAMPLE_XXXXXXXXXXXXXXXX
KEY2_EXAMPLE_YYYYYYYYYYYYYYYY
```

- Tambahkan video (format mp4/mov/mkv/avi) — aplikasi akan memvalidasi durasi, resolusi, dan bitrate sesuai aturan Adobe Stock.
- Pilih folder output.
- Pilih preset dan atur opsi (mute, delete original jika ingin menghapus file asli setelah sukses).
- Tekan `START PROCESSING`.

## Format file API keys
- Plain text, satu kunci per baris. Baris kosong dan baris yang diawali `#` akan diabaikan.

## Lisensi & Aktivasi
- Aplikasi saat ini menonaktifkan cek lisensi (lihat pesan "License not required" di UI).
- Ada fungsi untuk validasi lisensi terhadap `LICENSE_SERVER_URL`, tetapi tidak wajib digunakan.

## Catatan penting tentang file besar (GitHub)
- Repo ini saat ini berisi file `output/Topaz Video Upscale.exe` (~59 MB). GitHub memperingatkan file > 50 MB.
- Rekomendasi:
  - Gunakan Git LFS untuk file besar, atau
  - Hapus file besar dari repo (akan memerlukan rewrite history jika sudah dipush).

Contoh langkah menambahkan Git LFS (rekomendasi jika Anda ingin menyimpan file besar di repo):

```powershell
git lfs install
git lfs track "output/*.exe"
git add .gitattributes
git rm --cached "output/Topaz Video Upscale.exe"
git add "output/Topaz Video Upscale.exe"
git commit -m "Move exe to Git LFS"
git push
```

Jika Anda ingin menghapus file besar dari riwayat remote, gunakan `bfg` atau `git filter-repo`. Jika perlu, saya bisa bantu langkah ini.

## Troubleshooting singkat
- Error: `ImportError: No module named 'tkinter'` — jalankan installer Python dari python.org dan pastikan opsi Tcl/Tk dipilih.
- Error: `FFmpeg not found` — pastikan FFmpeg terinstal dan `ffmpeg.exe` berada di `PATH`.
- Jika `cv2.VideoCapture` gagal membaca file, pastikan format dan codec video didukung oleh OpenCV.

## Keamanan & API
- Jangan commit kunci API ke repo publik. Simpan file kunci (`api_keys.txt`) di luar repo atau tambahkan ke `.gitignore`.

## Perbaikan & kontribusi
- Kode ditulis sebagai satu file monolitik (`topaz_video_gui_pro.py`). Untuk kontribusi, pertimbangkan memisahkan modul (ui/, ffmpeg/, api/).

## Kontak
- Untuk pertanyaan lebih lanjut atau jika Anda ingin saya mengatur Git LFS / menghapus file besar dari riwayat,
  beri tahu saya dan saya akan bantu langkah demi langkah.

---
*Generated by maintainer assistant — README diperbarui dengan panduan instalasi dan menjalankan.*
# Topaz Video Upscaler - Adobe Stock Professional Edition

> A lightweight GUI wrapper to prepare and upload short videos to Topaz Labs' video API
> and re-encode outputs to meet Adobe Stock requirements.

## Ringkasan
- File utama: `topaz_video_gui_pro.py`
- UI: Tkinter (Dark theme)
- Fungsi utama: memilih video, membuat request ke API Topaz, mengunggah, menunggu proses,
  lalu mengunduh dan melakukan re-encode `ffmpeg` agar sesuai spesifikasi Adobe Stock.

## Prasyarat (yang harus diinstal)
- Python 3.8+ (disarankan 3.8 — 3.11)
- FFmpeg (full build) dan FFprobe — tambahkan folder `bin` FFmpeg ke `PATH`.
- Paket Python:

```powershell
py -m pip install --upgrade pip
py -m pip install opencv-python requests
```

Catatan:
- Tkinter biasanya disertakan pada installer resmi Python untuk Windows. Jika muncul error terkait `tkinter`,
  reinstall Python dengan opsi `tcl/tk` atau gunakan installer resmi dari python.org.
- `opencv-python` menyediakan `cv2` untuk membaca metadata video.

## File penting di repo
- `topaz_video_gui_pro.py` — aplikasi GUI utama.
- `adobe_stock_settings.json` — file settings (dipakai untuk menyimpan path API dan output).
- `license.dat` — berkas lisensi (repo saat ini menyertakan file ini; aplikasi sekarang menganggap lisensi
  tidak diperlukan, jadi file ini bersifat opsional).
- `output/Topaz Video Upscale.exe` — file binary besar yang saat ini sudah ada di repo; perhatikan ukuran.

## Cara menyiapkan lingkungan dan menjalankan

1. (Opsional) buat virtual environment:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate
```

2. Install dependensi Python:

```powershell
py -m pip install --upgrade pip
py -m pip install opencv-python requests
```

3. Pastikan `ffmpeg` dan `ffprobe` dapat diakses dari `PATH` (jalankan `ffmpeg -version`).

4. Jalankan aplikasi GUI:

```powershell
py .\topaz_video_gui_pro.py
```

5. Di aplikasi:
- Pilih file `API Keys` (plain text, satu kunci per baris). Contoh `api_keys.txt`:

```
KEY1_EXAMPLE_XXXXXXXXXXXXXXXX
KEY2_EXAMPLE_YYYYYYYYYYYYYYYY
```

- Tambahkan video (format mp4/mov/mkv/avi) — aplikasi akan memvalidasi durasi, resolusi, bitrate sesuai aturan Adobe Stock.
- Pilih folder output.
- Pilih preset dan atur opsi (mute, delete original jika ingin menghapus file asli setelah sukses).
- Tekan `START PROCESSING`.

## Format file API keys
- Plain text, satu kunci per baris. Baris kosong dan baris yang diawali `#` akan diabaikan.

## Lisensi & Aktivasi
- Aplikasi saat ini menonaktifkan cek lisensi (lihat pesan "License not required" di UI).
- Ada fungsi untuk validasi lisensi terhadap `LICENSE_SERVER_URL`, tetapi tidak wajib digunakan.

## Catatan penting tentang file besar (GitHub)
- Repo ini saat ini berisi file `output/Topaz Video Upscale.exe` (~59 MB). GitHub memperingatkan file > 50 MB.
- Rekomendasi:
  - Gunakan Git LFS untuk file besar, atau
  - Hapus file besar dari repo (akan memerlukan rewrite history jika sudah dipush).

Contoh langkah menambahkan Git LFS (rekomendasi jika Anda ingin menyimpan file besar di repo):

```powershell
git lfs install
git lfs track "output/*.exe"
git add .gitattributes
git rm --cached "output/Topaz Video Upscale.exe"
git add "output/Topaz Video Upscale.exe"
git commit -m "Move exe to Git LFS"
git push
```

Jika Anda ingin menghapus file besar dari riwayat remote, gunakan `bfg` atau `git filter-repo`. Jika perlu, saya bisa bantu langkah ini.

## Troubleshooting singkat
- Error: `ImportError: No module named 'tkinter'` — instal ulang Python resmi dengan Tcl/Tk atau pasang paket yang sesuai.
- Error: `FFmpeg not found` — pastikan FFmpeg terinstal dan `ffmpeg.exe` berada di `PATH`.
- Jika `cv2.VideoCapture` gagal membaca file, pastikan format dan codec video didukung oleh OpenCV (terkadang beberapa container/codec memerlukan FFmpeg-backed builds).

## Keamanan & API
- Jangan commit kunci API ke repo publik. Simpan file kunci (`api_keys.txt`) di luar repo atau tambahkan ke `.gitignore`.

## Perbaikan & kontribusi
- Kode ditulis sebagai satu file monolitik (`topaz_video_gui_pro.py`). Untuk kontribusi, pertimbangkan memisahkan modul (ui/, ffmpeg/, api/).

## Kontak
- Untuk pertanyaan lebih lanjut atau jika Anda ingin saya mengatur Git LFS / menghapus file besar dari riwayat,
  beri tahu saya dan saya akan bantu langkah demi langkah.

---
*Generated by maintainer assistant — README dasar untuk mempercepat penggunaan.*
