#!/usr/bin/env python3
"""
Topaz Video Upscaler - Adobe Stock Professional Edition v30
========================================================
Aplikasi khusus untuk menghasilkan video berkualitas tinggi 
yang memenuhi standar ketat Adobe Stock.

Features:
- Dark premium UI dengan animasi (dari v28)
- Preset khusus Adobe Stock (dari v28)
- Validasi Adobe Stock (dari v28)
- **Perbaikan Kualitas v29**: Menggabungkan logika `setpts`/`atempo` dari v26
  untuk memperbaiki bug durasi dan sinkronisasi audio.
- **Perbaikan Lisensi v29**: Menggabungkan logika lisensi `v21` (dengan action 'validate' 
  dan 'activate') untuk pencabutan (revoke) instan dari server.
- **Perbaikan Fitur v29**: Menambahkan kembali Toggle Mute & Hapus Asli,
  dan memperbaiki tombol Hapus Video.
- **Perbaikan API v29**: Menambahkan rotasi kunci API dan penghapusan kunci 402.
- **Perbaikan Bug v30**: Memperbaiki SyntaxError (missing 'except' block)
  di `reencode_video_adobe_optimized`.
"""

import os
import threading
import queue
import time
import subprocess
import uuid
import json
import webbrowser
import shutil
from datetime import datetime, date, timedelta
from typing import List, Dict, Tuple, Optional
import math

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    from tkinter import font as tkfont
except ImportError:
    raise ImportError("Tkinter tidak terinstal. Harap install tkinter terlebih dahulu.")

import cv2  # type: ignore
import requests

# ===== CONFIGURATION =====
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
LICENSE_SERVER_URL = "https://script.google.com/macros/s/AKfycbznSNUyIvFlh_sxaqrMT0bvLRYo321uukcNpXRKb0za_pUrfodr8nvIE2KDtC_2FGYoLg/exec"
LICENSE_PURCHASE_URL = "wa.me/6285764139959?text=Halo%2C%20saya%20ingin%20membeli%20lisensi%20Topaz%20Video%20Upscaler%20Adobe%20Stock%20Professional%20Edition." 
LICENSE_FILE = os.path.join(SCRIPT_DIR, "license.dat")
SETTINGS_FILE = os.path.join(SCRIPT_DIR, "adobe_stock_settings.json")

# Adobe Stock Requirements
ADOBE_MIN_BITRATE_4K = 35  # Mbps
ADOBE_MIN_BITRATE_1080P = 10  # Mbps
ADOBE_MIN_DURATION = 5  # seconds
ADOBE_MAX_DURATION = 60  # seconds

# ===== HELPER FUNCTIONS =====
def read_api_keys_from_file(path: str) -> List[str]:
    keys = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    keys.append(line)
    except Exception as exc:
        print(f"Gagal membaca file kunci API: {exc}")
    return keys

def get_video_metadata(video_path: str) -> Tuple[int, int, float, int, float, int]:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Gagal membuka: {video_path}")
    
    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = frame_count / fps if fps > 0 else 0
        size = os.path.getsize(video_path)
        return width, height, fps, frame_count, duration, size
    finally:
        cap.release()

def estimate_bitrate(file_size: int, duration: float) -> float:
    """Estimate bitrate in Mbps"""
    if duration <= 0:
        return 0
    bits = file_size * 8
    seconds = duration
    bitrate_bps = bits / seconds
    bitrate_mbps = bitrate_bps / (1024 * 1024)
    return bitrate_mbps

def pick_model_and_sharpen(width: int, height: int, fps: float, bitrate_mbps: float) -> Tuple[str, str]:
    """
    Pilih model Topaz dan level unsharp otomatis berdasarkan resolusi/bitrate/FPS sumber.
    Rule-of-thumb:
    - Sumber tinggi & bersih -> Proteus dengan unsharp lembut
    - Sumber bitrate rendah/soft -> Artemis dengan unsharp sedikit lebih kuat
    - Sumber FHD bitrate sedang/FPS rendah -> Iris dengan unsharp lembut
    """
    if bitrate_mbps <= 0:
        bitrate_mbps = 1.0
    is_uhd = width >= 3200 or height >= 1800
    is_fhd = width >= 1920 and height >= 1080
    is_low_res = width < 1280 or height < 720
    low_bitrate = bitrate_mbps < 6
    mid_bitrate = 6 <= bitrate_mbps < 12
    high_bitrate = bitrate_mbps >= 12

    model = "prob-4"  # Default ke Proteus
    amount = 0.60

    if is_low_res or low_bitrate:
        model = "ahq-12"   # Artemis untuk sumber soft/noisy
        amount = 0.70
    elif is_uhd and high_bitrate:
        model = "prob-4"   # Proteus untuk detail tinggi
        amount = 0.55
    elif is_fhd and mid_bitrate:
        if fps <= 30:
            model = "iris-3"  # Iris untuk tekstur halus FHD
            amount = 0.55
        else:
            model = "prob-4"
            amount = 0.60
    else:
        # Fallback umum
        model = "prob-4"
        amount = 0.65 if not high_bitrate else 0.58

    # Clamp agar tidak terlalu tajam
    amount = max(0.45, min(amount, 0.75))
    unsharp = f"unsharp=luma_msize_x=5:luma_amount={amount:.2f}"
    return model, unsharp

def normalize_fps(fps: float) -> float:
    """Normalize FPS to Adobe Stock standards"""
    if 23.5 <= fps < 24.5:
        return 23.976 # Lebih disukai daripada 24
    elif 24.5 <= fps < 25.5:
        return 25.0
    elif 29.5 <= fps < 30.5:
        return 29.97 # Lebih disukai daripada 30
    elif 49.5 <= fps < 50.5:
        return 50.0
    elif 59.5 <= fps < 60.5:
        return 59.94 # Lebih disukai daripada 60
    return round(fps, 3) # Fallback

def has_audio_stream(video_path: str, log_queue: queue.Queue) -> bool:
    try:
        cmd = ["ffprobe", "-v", "error", "-select_streams", "a:0", 
               "-show_entries", "stream=codec_type", "-of", 
               "default=noprint_wrappers=1:nokey=1", video_path]
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        result = subprocess.run(cmd, capture_output=True, text=True, 
                                check=True, creationflags=creation_flags)
        return "audio" in result.stdout.lower()
    except:
        return True # Asumsikan ada jika ffprobe gagal

def get_unique_filepath(output_path: str) -> str:
    if not os.path.exists(output_path):
        return output_path
    
    directory, filename = os.path.split(output_path)
    base_name, extension = os.path.splitext(filename)
    
    counter = 1
    while True:
        new_filename = f"{base_name}_{counter}{extension}"
        new_path = os.path.join(directory, new_filename)
        if not os.path.exists(new_path):
            return new_path
        counter += 1

# ===== TOPAZ API FUNCTIONS =====
def create_request(
    api_key: str, models: List[str], video_metadata: Tuple,
    out_width: int, out_height: int, out_fps: float,
    mute: bool, video_encoder: str, compression_level: str,
    video_profile: str, container: str) -> Dict:
    width, height, fps, frame_count, duration, size = video_metadata
    
    filters_payload = []
    for model_code in models:
        filters_payload.append({"model": model_code})
    
    payload = {
        "source": {
            "container": "mp4",
            "size": size,
            "duration": int(round(duration)),
            "frameCount": frame_count,
            "frameRate": fps,
            "resolution": {"width": width, "height": height}
        },
        "filters": filters_payload,
        "output": {
            "frameRate": out_fps, # Kirim FPS yang sudah dinormalisasi
            "audioTransfer": "None" if mute else "Copy",
            "audioCodec": "AAC",
            "dynamicCompressionLevel": compression_level,
            "resolution": {"width": out_width, "height": out_height},
            "container": container,
            "videoEncoder": video_encoder,
            "videoProfile": video_profile
        }
    }
    
    headers = {
        "X-API-Key": api_key,
        "accept": "application/json",
        "content-type": "application/json"
    }
    
    resp = requests.post("https://api.topazlabs.com/video/", 
                         headers=headers, json=payload)
    resp.raise_for_status()
    return resp.json()

def accept_request(api_key: str, request_id: str) -> Dict:
    url = f"https://api.topazlabs.com/video/{request_id}/accept"
    headers = {"X-API-Key": api_key, "accept": "application/json"}
    resp = requests.patch(url, headers=headers)
    resp.raise_for_status()
    return resp.json()

def upload_video_parts(upload_urls: List[str], video_path: str, 
                       log_queue: queue.Queue, progress_callback) -> List[Dict]:
    etags = []
    total_size = os.path.getsize(video_path)
    part_count = len(upload_urls)
    part_size = (total_size + part_count - 1) // part_count
    
    with open(video_path, "rb") as f:
        for idx, url in enumerate(upload_urls):
            start = idx * part_size
            end = min((idx + 1) * part_size, total_size)
            f.seek(start)
            data = f.read(end - start)
            
            progress_callback(f"Upload {idx + 1}/{part_count}", None)
            
            resp = requests.put(url, data=data, headers={"Content-Type": "video/mp4"})
            resp.raise_for_status()
            
            etag = resp.headers.get("ETag", "").strip('"')
            etags.append({"partNum": idx + 1, "eTag": etag})
    
    return etags

def complete_upload(api_key: str, request_id: str, results: List[Dict]) -> Dict:
    url = f"https://api.topazlabs.com/video/{request_id}/complete-upload/"
    headers = {
        "X-API-Key": api_key,
        "accept": "application/json",
        "content-type": "application/json"
    }
    payload = {"uploadResults": results}
    resp = requests.patch(url, headers=headers, json=payload)
    resp.raise_for_status()
    return resp.json()

def get_status(api_key: str, request_id: str) -> Dict:
    url = f"https://api.topazlabs.com/video/{request_id}/status"
    headers = {"X-API-Key": api_key, "accept": "application/json"}
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()

def download_video(url: str, output_path: str) -> None:
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

# --- PERBAIKAN V29: Menggunakan fungsi re-encode v26 (dengan setpts/atempo) ---
def reencode_video_adobe_optimized(input_path: str, output_path: str,
                                   codec: str, preset: str, crf: int,
                                   original_video_path: str, mute: bool,
                                   log_queue: queue.Queue,
                                   target_fps: float,
                                   original_duration: float, 
                                   desired_duration: float,
                                   sharp_filter: Optional[str] = None
                                   ) -> bool:
    log_queue.put(f"  Memulai re-encode ke {codec} dengan preset {preset} dan CRF {crf}...")
    if sharp_filter:
        log_queue.put(f"  Sharpen otomatis: {sharp_filter}")
    
    # Input 0: File temp (video)
    cmd = ["ffmpeg", "-y", "-i", input_path]
    
    # Periksa audio dari file asli *DAN* periksa opsi mute
    video_has_audio = has_audio_stream(original_video_path, log_queue) and not mute
    
    if video_has_audio:
        # Input 1: File asli (audio)
        cmd.extend(["-i", original_video_path])
        log_queue.put("  Mendeteksi audio di file asli, akan menyalin stream audio...")
    else:
        if mute: log_queue.put("  Opsi Mute Audio aktif, file akhir akan bisu.")
        else: log_queue.put("  Tidak ada audio di file asli, file akhir akan bisu.")

    def compose_video_filter(base: str) -> str:
        return f"{base},{sharp_filter}" if sharp_filter else base

    try:
        temp_duration = get_video_metadata(input_path)[4]

        if temp_duration > 0 and original_duration > 0:
            # 1. Faktor Kecepatan VIDEO: Untuk memperbaiki output Topaz
            video_speed_factor = temp_duration / desired_duration
            video_pts_factor = 1.0 / video_speed_factor
            log_queue.put(f"  Menyesuaikan durasi video dari {temp_duration:.2f}s ke {desired_duration:.2f}s (Faktor PTS: {video_pts_factor:.4f})...")
            
            if video_has_audio:
                # 2. Faktor Kecepatan AUDIO: Untuk meregangkan audio asli
                audio_speed_factor = original_duration / desired_duration
                log_queue.put(f"  Menyesuaikan durasi audio dari {original_duration:.2f}s ke {desired_duration:.2f}s (Faktor Atempo: {audio_speed_factor:.4f})...")

                atempo_filters = []
                while audio_speed_factor > 2.0:
                    atempo_filters.append("atempo=2.0")
                    audio_speed_factor /= 2.0
                while audio_speed_factor < 0.5:
                    atempo_filters.append("atempo=0.5")
                    audio_speed_factor /= 0.5
                if audio_speed_factor != 1.0: 
                    atempo_filters.append(f"atempo={audio_speed_factor:.4f}")
                
                atempo_filter_str = ",".join(atempo_filters) if atempo_filters else "anull"
                video_filter = compose_video_filter(f"setpts={video_pts_factor:.4f}*PTS")
                cmd.extend(["-filter_complex", f"[0:v]{video_filter}[v];[1:a]{atempo_filter_str}[a]", "-map", "[v]", "-map", "[a]"])
            else:
                log_queue.put("  Tidak ada audio, hanya video yang disesuaikan.")
                cmd.extend(["-filter:v", compose_video_filter(f"setpts={video_pts_factor:.4f}*PTS"), "-an"])
        else:
            # Logika fallback jika durasi tidak valid
            log_queue.put("  Durasi tidak valid, fallback ke salinan sederhana.")
            if video_has_audio:
                if sharp_filter:
                    cmd.extend(["-filter:v", sharp_filter, "-map", "0:v:0", "-map", "1:a:0", "-c:a", "copy"])
                else:
                    cmd.extend(["-map", "0:v:0", "-map", "1:a:0", "-c:a", "copy"])
            else:
                if sharp_filter:
                    cmd.extend(["-filter:v", sharp_filter, "-map", "0:v:0", "-an"])
                else:
                    cmd.extend(["-map", "0:v:0", "-an"])

    except Exception as e:
        log_queue.put(f"  Gagal menghitung faktor kecepatan: {e}")
        if video_has_audio:
            if sharp_filter:
                cmd.extend(["-filter:v", sharp_filter, "-map", "0:v:0", "-map", "1:a:0", "-c:a", "copy"])
            else:
                cmd.extend(["-map", "0:v:0", "-map", "1:a:0", "-c:a", "copy"])
        else:
            if sharp_filter:
                cmd.extend(["-filter:v", sharp_filter, "-map", "0:v:0", "-an"])
            else:
                cmd.extend(["-map", "0:v:0", "-an"])

    # Terapkan encoding video (spesifikasi Adobe Stock)
    # Tambahkan target bitrate & GOP sesuai resolusi output
    out_meta = get_video_metadata(input_path)
    out_w, out_h = out_meta[0], out_meta[1]
    target_maxrate = "20000k"
    target_bufsize = "40000k"
    if out_w >= 3800 or out_h >= 2100:
        target_maxrate = "50000k"
        target_bufsize = "100000k"
    elif out_w >= 1900 or out_h >= 1060:
        target_maxrate = "25000k"
        target_bufsize = "50000k"

    gop = None
    if target_fps:
        try:
            gop = max(1, int(round(target_fps * 2)))
        except Exception:
            gop = None

    cmd.extend([
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", str(crf),
        "-profile:v", "high",
        "-level", "4.2",
        "-pix_fmt", "yuv420p",
        "-colorspace", "bt709",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-movflags", "+faststart",
        "-maxrate", target_maxrate,
        "-bufsize", target_bufsize
    ])
    
    # Terapkan FPS HANYA jika ditentukan
    if target_fps is not None:
        log_queue.put(f"  Memaksa FPS output ke {target_fps}.")
        cmd.extend(["-r", str(target_fps)])
    if gop:
        cmd.extend(["-g", str(gop), "-keyint_min", str(gop)])

    # Terapkan audio
    if video_has_audio:
        cmd.extend(["-c:a", "aac", "-b:a", "320k", "-ar", "48000"])
    
    cmd.append(output_path)
    
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, 
                              encoding='utf-8', creationflags=creation_flags)
        if proc.returncode != 0:
            log_queue.put(f"FFmpeg error: {proc.stderr}")
            return False
        log_queue.put("Re-encode berhasil dengan Adobe Stock specs.")
        return True
    except FileNotFoundError:
        log_queue.put("FFmpeg tidak ditemukan!")
        return False
    except Exception as e:
        log_queue.put(f"Error: {e}")
        return False
# --- AKHIR PERBAIKAN V29 ---


# ===== CUSTOM UI COMPONENTS =====

# --- PERBAIKAN V29: Menambahkan kembali class ToggleSwitch yang hilang ---
class ToggleSwitch(tk.Canvas):
    def __init__(self, parent, variable, on_color="#0a84ff", off_color="#555", width=30, height=15, **kwargs):
        parent_bg = parent.cget('bg')
        canvas_bg = kwargs.pop('bg', parent_bg)
        super().__init__(parent, width=width, height=height,
                         highlightthickness=0, bd=0, bg=canvas_bg, **kwargs)
        
        self.variable = variable
        self.on_color = on_color
        self.off_color = off_color
        self.width = width
        self.height = height
        self.parent_bg = canvas_bg
        
        self.bind("<Button-1>", self._toggle)
        self.variable.trace_add("write", self._update_display)
        self._draw_switch()

    def _draw_switch(self):
        self.delete("all")
        radius = self.height / 2
        
        # Gunakan bg parent
        self.configure(bg=self.parent_bg)
        
        bg_color = self.on_color if self.variable.get() else self.off_color
        circle_x = self.width - radius if self.variable.get() else radius
        
        # Track
        self.create_oval(0, 0, self.height, self.height, fill=bg_color, outline=bg_color)
        self.create_oval(self.width - self.height, 0, self.width, self.height, fill=bg_color, outline=bg_color)
        self.create_rectangle(radius, 0, self.width - radius, self.height, fill=bg_color, outline=bg_color)
        
        # Handle
        self.create_oval(circle_x - radius + 2, 2, circle_x + radius - 2, self.height - 2, 
                         fill="white", outline="white")

    def _toggle(self, event=None): 
        self.variable.set(not self.variable.get())
    
    def _update_display(self, *args): 
        self._draw_switch()
# -----------------------------------------------------


class AnimatedButton(tk.Canvas):
    def __init__(self, parent, text="", command=None, width=200, height=45,
                 bg_color="#1a1a1a", hover_color="#2a2a2a", 
                 active_color="#0066ff", text_color="#ffffff", **kwargs):
        super().__init__(parent, width=width, height=height, 
                         highlightthickness=0, bd=0, **kwargs)
        
        self.width = width
        self.height = height
        self.text = text
        self.command = command
        self.bg_color = bg_color
        self.hover_color = hover_color
        self.active_color = active_color
        self.text_color = text_color
        self.current_color = bg_color
        self.is_animating = False
        self.enabled = True
        
        self.configure(bg=parent['bg'])
        self.draw_button()
        
        self.bind("<Enter>", self.on_enter)
        self.bind("<Leave>", self.on_leave)
        self.bind("<Button-1>", self.on_click)
        self.bind("<ButtonRelease-1>", self.on_release)
    
    def draw_button(self):
        self.delete("all")
        
        # --- PERBAIKAN V29: Menggunakan create_rounded_rect ---
        self.create_rounded_rect(0, 0, self.width, self.height, 8,
                                 fill=self.current_color, outline="",
                                 tags="bg", width=0)
        # ----------------------------------------------------
                                 
        # Text
        self.create_text(self.width/2, self.height/2, text=self.text,
                         fill=self.text_color, font=("Segoe UI", 11, "bold"),
                         tags="text")
    
    # --- PERBAIKAN V29: Helper untuk rounded rectangle ---
    def create_rounded_rect(self, x1, y1, x2, y2, r, **kwargs):
        """Gambar rounded rectangle (untuk UI yang lebih baik)"""
        points = [x1+r, y1, x1+r, y1, x2-r, y1, x2-r, y1,
                  x2, y1, x2, y1+r, x2, y1+r, x2, y2-r,
                  x2, y2-r, x2, y2, x2-r, y2, x2-r, y2,
                  x1+r, y2, x1+r, y2, x1, y2, x1, y2-r,
                  x1, y2-r, x1, y1+r, x1, y1+r, x1, y1]
        return self.create_polygon(points, **kwargs, smooth=True)
    # ---------------------------------------------------
    
    def animate_color(self, target_color, steps=10):
        if self.is_animating:
            return
        self.is_animating = True
        
        # Simple color transition (no real animation for simplicity)
        self.current_color = target_color
        self.draw_button()
        self.is_animating = False
    
    def on_enter(self, event):
        if self.enabled:
            self.animate_color(self.hover_color)
    
    def on_leave(self, event):
        if self.enabled:
            self.animate_color(self.bg_color)
    
    def on_click(self, event):
        if self.enabled:
            self.animate_color(self.active_color)
    
    def on_release(self, event):
        if self.enabled and self.command:
            self.command()
            self.animate_color(self.hover_color)
    
    def set_enabled(self, enabled):
        self.enabled = enabled
        if not enabled:
            self.current_color = "#0a0a0a"
            self.text_color = "#444444"
        else:
            self.current_color = self.bg_color
            self.text_color = "#ffffff"
        self.draw_button()

class ModernProgressBar(tk.Canvas):
    def __init__(self, parent, width=500, height=30, **kwargs):
        super().__init__(parent, width=width, height=height,
                         highlightthickness=0, bd=0, **kwargs)
        self.width = width
        self.height = height
        self.progress = 0
        self.configure(bg=parent['bg'])
        self.draw_progress()
    
    def draw_progress(self):
        self.delete("all")
        # Background
        self.create_rectangle(0, 10, self.width, 20,
                              fill="#0a0a0a", outline="")
        # Progress
        if self.progress > 0:
            progress_width = (self.width * self.progress / 100)
            self.create_rectangle(0, 10, progress_width, 20,
                                  fill="#0066ff", outline="")
            # Glow effect
            self.create_rectangle(max(0, progress_width-20), 8, progress_width, 22,
                                  fill="#0088ff", outline="", stipple="gray50")
        # Text
        self.create_text(self.width/2, self.height/2,
                         text=f"{self.progress:.1f}%",
                         fill="#ffffff", font=("Segoe UI", 10, "bold"))
    
    def set_progress(self, value):
        self.progress = max(0, min(100, value))
        self.draw_progress()

# ===== MAIN APPLICATION =====
class AdobeStockUpscaler(tk.Tk):
    def __init__(self):
        super().__init__()
        
        # Window setup
        self.title("Topaz Video Upscaler - Adobe Stock Pro")
        self.geometry("1100x700")
        self.minsize(1000, 650)
        
        # Dark theme colors
        self.configure(bg="#0a0a0a")

        # Set custom window icon if available
        icon_path = os.path.join(SCRIPT_DIR, "logo.ico")
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception as e:
                print(f"Gagal set ikon: {e}")
        
        # Colors
        self.colors = {
            'bg': '#0a0a0a',
            'panel': '#111111',
            'card': '#1a1a1a',
            'border': '#2a2a2a',
            'text': '#ffffff',
            'text_dim': '#888888',
            'accent': '#0066ff',
            'success': '#00ff88',
            'warning': '#ffaa00',
            'error': '#ff3366'
        }
        
        # Variables
        self.api_file_path = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.input_files = [] # Digunakan oleh UI baru
        self.api_keys = [] # Digunakan oleh UI baru
        
        # --- PERBAIKAN V29: Menambahkan variabel dari v26 ---
        self.enhancement_model_var = tk.StringVar()
        self.interp_model_var = tk.StringVar(value="None")
        self.slow_motion_var = tk.StringVar(value="1x (Normal)")
        self.fps_var = tk.StringVar(value="Original") # Default baru (user dapat pilih)
        self.resolution_var = tk.StringVar(value="Original")
        
        self.mute_var = tk.BooleanVar(value=False)
        self.delete_original_var = tk.BooleanVar(value=False)
        # -------------------------------------------------

        self.preset_var = tk.StringVar()
        
        # Processing state
        self.is_processing = False
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.pause_event.set()
        
        # License (disederhanakan: selalu dianggap valid seperti Topaz.py)
        self.license_valid = tk.BooleanVar(value=True)
        self.ffmpeg_ready = tk.BooleanVar(value=False)
        self.last_license_check_date = date.min # v29
        
        # Queues
        self.log_queue = queue.Queue()
        self.log_history = []
        self.log_window = None
        self.log_text_widget = None
        
        # Adobe Stock Presets
        self.adobe_presets = {
            "Smart Auto (Model + Sharpen)": {
                "model": "auto",      # akan dipilih dari pick_model_and_sharpen
                "resolution": "User", # user pilih sendiri
                "compression": "High",
                "preset": "slow",     # ffmpeg preset
                "crf": 12             # default, bisa di-adjust di runtime
            }
        }

        self.preset_var.set("Smart Auto (Model + Sharpen)")

        # --- PERBAIKAN V29: Map untuk model v26 ---
        self.enh_model_map = {
            "Proteus (prob-4)": "prob-4",
            "Artemis (ahq-12)": "ahq-12",
            "Iris (iris-3)": "iris-3"
            # Tambahkan model lain jika ada di preset Anda
        }
        self.interp_model_map = {
            "None": "none"
            # Saat ini tidak ada interpolasi di preset, tapi ini untuk masa depan
        }
        # ----------------------------------------
        
        # Build UI
        self._build_ui()
        self._load_settings()
        self._check_license()
        
        # Start update loop
        self.after(100, self._update_ui)
        
        # Window close
        self.protocol("WM_DELETE_WINDOW", self._on_closing)
    
    def _build_ui(self):
        # Main container
        main_container = tk.Frame(self, bg=self.colors['bg'])
        main_container.pack(fill='both', expand=True, padx=20, pady=20)
        
        # Header
        self._create_header(main_container)
        
        # Content area - 2 columns
        content_frame = tk.Frame(main_container, bg=self.colors['bg'])
        content_frame.pack(fill='both', expand=True, pady=(20, 0))
        
        # Left column - Input/Output
        left_frame = tk.Frame(content_frame, bg=self.colors['bg'])
        left_frame.pack(side='left', fill='both', expand=True, padx=(0, 10))
        
        self._create_input_section(left_frame)
        self._create_output_section(left_frame)
        self._create_preset_section(left_frame)
        
        # Right column - Processing
        right_frame = tk.Frame(content_frame, bg=self.colors['bg'])
        right_frame.pack(side='right', fill='both', expand=True, padx=(10, 0))
        
        self._create_queue_section(right_frame)
        self._create_progress_section(right_frame)
        self._create_control_section(right_frame)
    
    def _create_header(self, parent):
        # Tinggikan header agar subtitle tidak terpotong
        header = tk.Frame(parent, bg=self.colors['panel'], height=80)
        header.pack(fill='x')
        header.pack_propagate(False)
        
        # Logo/Title
        title_frame = tk.Frame(header, bg=self.colors['panel'])
        title_frame.pack(side='left', padx=20, pady=10)
        
        tk.Label(title_frame, text="TOPAZ VIDEO UPSCALER",
                 font=("Segoe UI", 16, "bold"),
                 fg=self.colors['text'], bg=self.colors['panel']).pack(anchor='w')
        tk.Label(title_frame, text="Adobe Stock Professional Edition",
                 font=("Segoe UI", 10),
                 fg=self.colors['text_dim'], bg=self.colors['panel']).pack(anchor='w')
        
        # Status indicators
        status_frame = tk.Frame(header, bg=self.colors['panel'])
        status_frame.pack(side='right', padx=20, pady=15)
        
        self.license_indicator = tk.Label(status_frame, text="● LICENSE",
                                          font=("Segoe UI", 9, "bold"),
                                          fg=self.colors['error'],
                                          bg=self.colors['panel'])
        self.license_indicator.pack(side='left', padx=10)
        
        self.api_indicator = tk.Label(status_frame, text="● API",
                                      font=("Segoe UI", 9, "bold"),
                                      fg=self.colors['error'],
                                      bg=self.colors['panel'])
        self.api_indicator.pack(side='left', padx=10)
        
        self.ffmpeg_indicator = tk.Label(status_frame, text="● FFMPEG",
                                         font=("Segoe UI", 9, "bold"),
                                         fg=self.colors['error'],
                                         bg=self.colors['panel'])
        self.ffmpeg_indicator.pack(side='left', padx=10)
    
    def _create_input_section(self, parent):
        # Card frame
        card = tk.Frame(parent, bg=self.colors['card'])
        card.pack(fill='x', pady=(0, 15))
        
        tk.Label(card, text="INPUT FILES", font=("Segoe UI", 10, "bold"),
                 fg=self.colors['text_dim'], bg=self.colors['card']).pack(anchor='w', padx=15, pady=(10, 5))
        
        # API Key
        api_frame = tk.Frame(card, bg=self.colors['card'])
        api_frame.pack(fill='x', padx=15, pady=5)
        
        self.api_entry = tk.Entry(api_frame, textvariable=self.api_file_path,
                                  bg=self.colors['panel'], fg=self.colors['text'],
                                  insertbackground=self.colors['text'],
                                  relief='flat', font=("Segoe UI", 10))
        self.api_entry.pack(side='left', fill='x', expand=True)
        
        tk.Button(api_frame, text="Select API Keys",
                  command=self._choose_api_file,
                  bg=self.colors['border'], fg=self.colors['text'],
                  relief='flat', font=("Segoe UI", 9),
                  padx=15, pady=5).pack(side='right', padx=(5, 0))
        
        # Add videos button
        self.add_videos_btn = AnimatedButton(card, text="+ ADD VIDEOS",
                                             command=self._choose_videos,
                                             width=470, height=40,
                                             bg_color=self.colors['accent'],
                                             hover_color="#0088ff")
        self.add_videos_btn.pack(pady=10)
    
    def _create_output_section(self, parent):
        card = tk.Frame(parent, bg=self.colors['card'])
        card.pack(fill='x', pady=(0, 15))
        
        tk.Label(card, text="OUTPUT FOLDER", font=("Segoe UI", 10, "bold"),
                 fg=self.colors['text_dim'], bg=self.colors['card']).pack(anchor='w', padx=15, pady=(10, 5))
        
        out_frame = tk.Frame(card, bg=self.colors['card'])
        out_frame.pack(fill='x', padx=15, pady=(5, 15))
        
        self.output_entry = tk.Entry(out_frame, textvariable=self.output_dir,
                                     bg=self.colors['panel'], fg=self.colors['text'],
                                     insertbackground=self.colors['text'],
                                     relief='flat', font=("Segoe UI", 10))
        self.output_entry.pack(side='left', fill='x', expand=True)
        
        tk.Button(out_frame, text="Browse",
                  command=self._choose_output,
                  bg=self.colors['border'], fg=self.colors['text'],
                  relief='flat', font=("Segoe UI", 9),
                  padx=15, pady=5).pack(side='right', padx=(5, 0))

        # --- PERBAIKAN V29/V31: Toggle Hapus & Mute ---
        toggle_frame = tk.Frame(card, bg=self.colors['card'])
        toggle_frame.pack(fill='x', padx=15, pady=(0, 10))
        
        ToggleSwitch(toggle_frame, variable=self.delete_original_var,
                     on_color=self.colors['error'], off_color="#555",
                     bg=self.colors['card']).pack(side="left")
        tk.Label(toggle_frame, text="Delete original video after successful upscale",
                 font=("Segoe UI", 9), fg=self.colors['text'], bg=self.colors['card']
                 ).pack(side="left", padx=5)
        
        ToggleSwitch(toggle_frame, variable=self.mute_var,
                     on_color=self.colors['accent'], off_color="#555",
                     bg=self.colors['card']).pack(side="left", padx=(30, 0))
        tk.Label(toggle_frame, text="Mute audio in final output",
                 font=("Segoe UI", 9), fg=self.colors['text'], bg=self.colors['card']
                 ).pack(side="left", padx=5)
        # ------------------------------------------------
    
    def _create_preset_section(self, parent):
        card = tk.Frame(parent, bg=self.colors['card'])
        card.pack(fill='x')
        
        tk.Label(card, text="ADOBE STOCK PRESET", font=("Segoe UI", 10, "bold"),
                 fg=self.colors['text_dim'], bg=self.colors['card']).pack(anchor='w', padx=15, pady=(10, 5))
        
        # Preset selector
        preset_frame = tk.Frame(card, bg=self.colors['card'])
        preset_frame.pack(fill='x', padx=15, pady=(2, 4))
        
        for i, preset_name in enumerate(self.adobe_presets.keys()):
            rb = tk.Radiobutton(preset_frame, text=preset_name,
                                variable=self.preset_var, value=preset_name,
                                bg=self.colors['card'], fg=self.colors['text'],
                                activebackground=self.colors['card'],
                                activeforeground=self.colors['accent'],
                                selectcolor=self.colors['panel'],
                                font=("Segoe UI", 10),
                                command=self._on_preset_change)
            rb.pack(anchor='w', pady=0)
        
        # Info panel
        self.preset_info = tk.Label(card, text="", font=("Segoe UI", 9),
                                    fg=self.colors['text_dim'], bg=self.colors['card'],
                                    justify='left')
        self.preset_info.pack(anchor='w', padx=15, pady=(0, 6))
        self._update_preset_info()

        # Dark combobox style (supaya selaras tema gelap)
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(
            "Dark.TCombobox",
            fieldbackground=self.colors['panel'],
            background=self.colors['panel'],
            foreground=self.colors['text'],
            arrowcolor=self.colors['text']
        )
        style.map("Dark.TCombobox",
                  fieldbackground=[("readonly", self.colors['panel'])],
                  foreground=[("readonly", self.colors['text'])])

        # Output resolution selector (lebih rapat & ringkas)
        res_frame = tk.Frame(card, bg=self.colors['card'])
        res_frame.pack(fill='x', padx=15, pady=(2, 6))
        tk.Label(res_frame, text="OUTPUT RESOLUTION", font=("Segoe UI", 9, "bold"),
                 fg=self.colors['text_dim'], bg=self.colors['card']).pack(anchor='w')
        res_options = ["Original", "4K (3840x2160)", "1080p (1920x1080)"]
        res_combo = ttk.Combobox(res_frame, textvariable=self.resolution_var, values=res_options,
                     state="readonly", style="Dark.TCombobox")
        res_combo.pack(fill='x', pady=1)
        res_combo.bind("<<ComboboxSelected>>", lambda e: self._update_preset_info())
        for evt in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            res_combo.bind(evt, lambda e: "break")

        # FPS selector
        fps_frame = tk.Frame(card, bg=self.colors['card'])
        fps_frame.pack(fill='x', padx=15, pady=(0, 6))
        tk.Label(fps_frame, text="OUTPUT FPS", font=("Segoe UI", 9, "bold"),
                 fg=self.colors['text_dim'], bg=self.colors['card']).pack(anchor='w')
        fps_options = ["Original", "23.976", "24", "25", "29.97", "30", "50", "59.94", "60"]
        fps_combo = ttk.Combobox(fps_frame, textvariable=self.fps_var, values=fps_options,
                     state="readonly", style="Dark.TCombobox")
        fps_combo.pack(fill='x', pady=1)
        fps_combo.bind("<<ComboboxSelected>>", lambda e: self._update_preset_info())
        for evt in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            fps_combo.bind(evt, lambda e: "break")
        
    
    def _create_queue_section(self, parent):
        card = tk.Frame(parent, bg=self.colors['card'], height=200)
        card.pack(fill='both', expand=True, pady=(0, 15))
        card.pack_propagate(False)
        
        tk.Label(card, text="PROCESSING QUEUE", font=("Segoe UI", 10, "bold"),
                 fg=self.colors['text_dim'], bg=self.colors['card']).pack(anchor='w', padx=15, pady=(10, 5))
        
        # Queue listbox
        list_frame = tk.Frame(card, bg=self.colors['panel'])
        list_frame.pack(fill='both', expand=True, padx=15, pady=(5, 15))
        
        self.queue_listbox = tk.Listbox(list_frame, bg=self.colors['panel'],
                                        fg=self.colors['text'],
                                        selectbackground=self.colors['accent'],
                                        selectforeground=self.colors['text'],
                                        relief='flat', font=("Segoe UI", 9))
        self.queue_listbox.pack(fill='both', expand=True)
        
        # Queue controls
        queue_ctrl = tk.Frame(card, bg=self.colors['card'])
        queue_ctrl.pack(fill='x', padx=15, pady=(0, 10))
        
        # --- PERBAIKAN V29: Menghubungkan tombol hapus ---
        self.remove_btn = tk.Button(queue_ctrl, text="Remove Selected",
                  command=self._remove_selected,
                  bg=self.colors['border'], fg=self.colors['text'],
                  relief='flat', font=("Segoe UI", 9),
                  padx=10, pady=3)
        self.remove_btn.pack(side='left', padx=(0, 5))
        
        self.clear_btn = tk.Button(queue_ctrl, text="Clear All",
                  command=self._clear_queue,
                  bg=self.colors['border'], fg=self.colors['text'],
                  relief='flat', font=("Segoe UI", 9),
                  padx=10, pady=3)
        self.clear_btn.pack(side='left')
        # ---------------------------------------------
        
        self.queue_count = tk.Label(queue_ctrl, text="0 videos",
                                    font=("Segoe UI", 9),
                                    fg=self.colors['text_dim'],
                                    bg=self.colors['card'])
        self.queue_count.pack(side='right')
    
    def _create_progress_section(self, parent):
        card = tk.Frame(parent, bg=self.colors['card'])
        card.pack(fill='x', pady=(0, 15))
        
        tk.Label(card, text="PROGRESS", font=("Segoe UI", 10, "bold"),
                 fg=self.colors['text_dim'], bg=self.colors['card']).pack(anchor='w', padx=15, pady=(10, 5))
        
        # Current file
        self.current_file_label = tk.Label(card, text="Ready to process",
                                           font=("Segoe UI", 11),
                                           fg=self.colors['text'],
                                           bg=self.colors['card'])
        self.current_file_label.pack(anchor='w', padx=15, pady=5)
        
        # Progress bar
        self.progress_bar = ModernProgressBar(card, width=470, height=30,
                                              bg=self.colors['card'])
        self.progress_bar.pack(pady=10)
        
        # Status
        self.status_label = tk.Label(card, text="Waiting...",
                                     font=("Segoe UI", 10),
                                     fg=self.colors['text_dim'],
                                     bg=self.colors['card'])
        self.status_label.pack(anchor='w', padx=15, pady=(5, 15))
        
        # Quality indicators
        quality_frame = tk.Frame(card, bg=self.colors['card'])
        quality_frame.pack(fill='x', padx=15, pady=(0, 15))
        
        self.quality_checks = {
            'Resolution': tk.Label(quality_frame, text="○ Resolution",
                                   font=("Segoe UI", 9),
                                   fg=self.colors['text_dim'],
                                   bg=self.colors['card']),
            'Bitrate': tk.Label(quality_frame, text="○ Bitrate",
                                  font=("Segoe UI", 9),
                                  fg=self.colors['text_dim'],
                                  bg=self.colors['card']),
            'Duration': tk.Label(quality_frame, text="○ Duration",
                                   font=("Segoe UI", 9),
                                   fg=self.colors['text_dim'],
                                   bg=self.colors['card'])
        }
        
        for label in self.quality_checks.values():
            label.pack(side='left', padx=(0, 15))
    
    def _create_control_section(self, parent):
        card = tk.Frame(parent, bg=self.colors['card'])
        card.pack(fill='x')
        
        # Main controls
        ctrl_frame = tk.Frame(card, bg=self.colors['card'])
        ctrl_frame.pack(pady=15)
        
        self.start_btn = AnimatedButton(ctrl_frame, text="START PROCESSING",
                                        command=self._start_processing,
                                        width=150, height=45,
                                        bg_color=self.colors['success'],
                                        hover_color="#00ffaa",
                                        active_color="#00dd66")
        self.start_btn.grid(row=0, column=0, padx=5)
        
        self.pause_btn = AnimatedButton(ctrl_frame, text="PAUSE",
                                        command=self._toggle_pause,
                                        width=150, height=45,
                                        bg_color=self.colors['warning'],
                                        hover_color="#ffcc00")
        self.pause_btn.grid(row=0, column=1, padx=5)
        self.pause_btn.set_enabled(False)
        
        self.stop_btn = AnimatedButton(ctrl_frame, text="STOP",
                                       command=self._stop_processing,
                                       width=150, height=45,
                                       bg_color=self.colors['error'],
                                       hover_color="#ff5577")
        self.stop_btn.grid(row=0, column=2, padx=5)
        self.stop_btn.set_enabled(False)
        
        # Log button
        tk.Button(card, text="View Processing Log",
                  command=self._open_log,
                  bg=self.colors['border'], fg=self.colors['text'],
                  relief='flat', font=("Segoe UI", 9),
                  padx=20, pady=8).pack(pady=(0, 15))
    
    def _update_preset_info(self):
        preset = self.adobe_presets.get(self.preset_var.get(), {})
        info_text = "Smart auto memilih model & unsharp otomatis per video.\n"
        info_text += f"Resolution: {self.resolution_var.get()} (user)\n"
        info_text += f"FPS: {self.fps_var.get()} (user)\n"
        info_text += f"FFmpeg: preset {preset.get('preset', 'N/A')}, CRF default {preset.get('crf', 'N/A')}"
        self.preset_info.config(text=info_text)
    
    def _on_preset_change(self):
        self._update_preset_info()
        self._log(f"Preset changed: {self.preset_var.get()}")
    
    def _validate_video_for_adobe(self, video_path: str) -> Tuple[bool, str]:
        """Validate video meets Adobe Stock requirements"""
        try:
            width, height, fps, frames, duration, size = get_video_metadata(video_path)
            
            errors = []
            
            # Duration check
            if duration < ADOBE_MIN_DURATION:
                errors.append(f"Duration too short ({duration:.1f}s < {ADOBE_MIN_DURATION}s)")
            elif duration > ADOBE_MAX_DURATION:
                errors.append(f"Duration too long ({duration:.1f}s > {ADOBE_MAX_DURATION}s)")
            
            # Resolution check (must be standard)
            valid_resolutions = [(1920, 1080), (3840, 2160), (1280, 720)]
            if (width, height) not in valid_resolutions:
                if width < 1920 or height < 1080:
                    errors.append(f"Resolution too low ({width}x{height})")
            
            if errors:
                return False, "; ".join(errors)
            return True, "OK"
            
        except Exception as e:
            return False, str(e)
    
    def _choose_api_file(self):
        path = filedialog.askopenfilename(
            title="Select API Keys File",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if path:
            self.api_file_path.set(path)
            self.api_keys = read_api_keys_from_file(path)
            self._log(f"Loaded {len(self.api_keys)} API keys")
            self.api_indicator.config(fg=self.colors['success'] if self.api_keys else self.colors['error'])
            self._update_controls()
    
    def _choose_videos(self):
        files = filedialog.askopenfilenames(
            title="Select Videos",
            filetypes=[("Video files", "*.mp4 *.mov *.avi *.mkv"), ("All files", "*.*")]
        )
        for file in files:
            if file not in self.input_files:
                valid, msg = self._validate_video_for_adobe(file)
                if valid:
                    self.input_files.append(file)
                    self.queue_listbox.insert(tk.END, f" {os.path.basename(file)}")
                    self._log(f"Added: {os.path.basename(file)}")
                else:
                    self._log(f"Rejected {os.path.basename(file)}: {msg}")
                    messagebox.showwarning("Adobe Stock Validation",
                                           f"{os.path.basename(file)} doesn't meet Adobe Stock requirements:\n{msg}")
        
        self._update_queue_count()
        self._update_controls()
    
    def _choose_output(self):
        folder = filedialog.askdirectory(title="Select Output Folder")
        if folder:
            self.output_dir.set(folder)
            self._log(f"Output folder: {folder}")
            self._update_controls()
    
    # --- PERBAIKAN V29: Logika hapus dari v15 ---
    def _remove_selected(self) -> None:
        """Menghapus item yang dipilih dari listbox DAN data source."""
        selected_indices = self.queue_listbox.curselection()
        if not selected_indices:
            messagebox.showinfo("Info", "Pilih video yang ingin dihapus dari daftar.")
            return

        files_to_remove_paths = set()
        for i in sorted(selected_indices, reverse=True):
            try:
                path = self.input_files.pop(i)
                files_to_remove_paths.add(path)
            except IndexError:
                self._log(f"Error: Indeks {i} tidak ditemukan saat menghapus.")

        if files_to_remove_paths:
            self._update_queue_listbox() # Refresh UI
            self._log(f"{len(files_to_remove_paths)} video dihapus dari daftar.")
        
        self._update_controls()

    def _clear_queue(self) -> None:
        """Menghapus semua item dari listbox DAN data source."""
        self.input_files.clear()
        self._update_queue_listbox() # Refresh UI
        self._log("Semua video dihapus dari daftar.")
        self._update_controls()
    
    def _update_queue_listbox(self):
        """Menyegarkan listbox UI berdasarkan data source `self.input_files`."""
        self.queue_listbox.delete(0, tk.END)
        for f in self.input_files:
            self.queue_listbox.insert(tk.END, f" {os.path.basename(f)}")
        self._update_queue_count()
    # ---------------------------------------------
    
    def _update_queue_count(self):
        count = len(self.input_files)
        self.queue_count.config(text=f"{count} video{'s' if count != 1 else ''}")
    
    def _update_controls(self):
        can_start = (
            len(self.input_files) > 0 and
            len(self.api_keys) > 0 and
            os.path.isdir(self.output_dir.get()) and
            not self.is_processing
        )
        self.start_btn.set_enabled(can_start)
    
    def _check_dependencies(self) -> bool:
        self._log("Memeriksa dependensi FFmpeg/FFprobe...")
        try:
            creation_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True, creationflags=creation_flags)
            self._log("  -> FFmpeg ditemukan.")
            subprocess.run(["ffprobe", "-version"], capture_output=True, check=True, creationflags=creation_flags)
            self._log("  -> FFprobe ditemukan.")
            self.ffmpeg_ready.set(True)
            self.ffmpeg_indicator.config(fg=self.colors['success'])
            return True
        except FileNotFoundError:
            self._log("  ERROR: FFmpeg/FFprobe tidak ditemukan di PATH.")
            self.ffmpeg_ready.set(False)
            self.ffmpeg_indicator.config(fg=self.colors['error'])
            messagebox.showerror("Missing Dependencies",
                                 "FFmpeg dan/atau FFprobe tidak ditemukan.\n\n"
                                 "Harap instal FFmpeg (full build) dan pastikan folder 'bin'-nya ada di sistem PATH Anda.")
            return False
        except Exception as e:
            self._log(f"  ERROR: Gagal saat memeriksa FFmpeg: {e}")
            self.ffmpeg_ready.set(False)
            self.ffmpeg_indicator.config(fg=self.colors['error'])
            messagebox.showerror("Error Dependensi", f"Error saat memeriksa FFmpeg: {e}")
            return False
    
    def _start_processing(self):
        if not self._check_dependencies():
            return
        
        self.is_processing = True
        self.stop_event.clear()
        self.pause_event.set()
        
        self.start_btn.set_enabled(False)
        self.pause_btn.set_enabled(True)
        self.stop_btn.set_enabled(True)
        
        threading.Thread(target=self._process_videos, daemon=True).start()
    
    def _toggle_pause(self):
        if self.pause_event.is_set():
            self.pause_event.clear()
            self.pause_btn.text = "RESUME"
            self.pause_btn.draw_button()
            self._log("Processing paused")
        else:
            self.pause_event.set()
            self.pause_btn.text = "PAUSE"
            self.pause_btn.draw_button()
            self._log("Processing resumed")
    
    def _stop_processing(self):
        if messagebox.askyesno("Confirm", "Stop processing all videos?"):
            self.stop_event.set()
            self.pause_event.set()
            self._log("Stopping...")
    
    def _update_progress(self, status: str, progress: Optional[float] = None):
        self.status_label.config(text=status)
        if progress is not None:
            self.progress_bar.set_progress(progress)
    
    def _update_quality_check(self, check: str, passed: bool, message: str = ""):
        if check in self.quality_checks:
            color = self.colors['success'] if passed else self.colors['error']
            symbol = "●" if passed else "○"
            text = f"{symbol} {check} {message}"
            self.quality_checks[check].config(text=text, fg=color)
    
    def _get_machine_id(self) -> str:
        """Menghasilkan ID mesin sederhana berbasis MAC."""
        return hex(uuid.getnode())

    # --- PERBAIKAN V29: Mengimpor logika v21 ---
    def _validate_key_on_server(self, key: str, machine_id: str, action: str = "validate") -> Optional[Dict]:
        self.status_label.config(text="Memvalidasi lisensi...")
        payload = {'license_key': key, 'machine_id': machine_id, 'action': action}
        
        try:
            response = requests.post(LICENSE_SERVER_URL, json=payload, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "valid":
                    self.status_label.config(text="Lisensi valid!")
                    return data
                else:
                    messagebox.showerror("Lisensi Tidak Valid", data.get("message", "Kunci tidak valid."))
            else:
                messagebox.showerror("Error Server", f"Gagal menghubungi server. Status: {response.status_code}")
        except requests.exceptions.RequestException as e:
            self._log(f"Gagal menghubungi server lisensi: {e}")
            self.status_label.config(text="Gagal menghubungi server lisensi.")
        return None

    def _check_license(self):
        """Lisensi dinonaktifkan: selalu aktif dan tidak perlu file/aktivasi."""
        self.license_valid.set(True)
        self.license_indicator.config(text="● LICENSE (Not required)", fg=self.colors['success'])
        self.status_label.config(text="Lisensi tidak diperlukan")
        self._log("Lisensi dinonaktifkan: selalu aktif.")
        self._update_controls()

    def _show_license_dialog(self):
        """Dialog lisensi dinonaktifkan."""
        self._log("Lisensi tidak diperlukan, dialog tidak ditampilkan.")

    def _on_dialog_close(self):
        """Tidak ada efek karena lisensi dinonaktifkan."""
        self._log("Lisensi tidak diperlukan.")
    
    def _open_log(self):
        if self.log_window is not None and self.log_window.winfo_exists():
            self.log_window.lift()
            return

        self.log_window = tk.Toplevel(self)
        self.log_window.title("Processing Log")
        self.log_window.geometry("600x400")
        self.log_window.configure(bg=self.colors['bg'])
        
        text_widget = tk.Text(self.log_window, bg=self.colors['panel'],
                              fg=self.colors['text'],
                              insertbackground=self.colors['text'],
                              relief='flat', font=("Consolas", 9))
        text_widget.pack(fill='both', expand=True, padx=10, pady=10)
        self.log_text_widget = text_widget
        
        for msg in self.log_history:
            text_widget.insert('end', msg + '\n')
        text_widget.see('end')
        text_widget.config(state='disabled')
        
        self.log_window.protocol("WM_DELETE_WINDOW", self._on_log_window_close)

    def _on_log_window_close(self):
        if self.log_window:
            self.log_window.destroy()
        self.log_window = None
        self.log_text_widget = None
    
    def _log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_msg = f"[{timestamp}] {message}"
        self.log_queue.put(log_msg)
    
    def _update_ui(self):
        while not self.log_queue.empty():
            msg = self.log_queue.get()
            self.log_history.append(msg)
            if len(self.log_history) > 1000:
                self.log_history.pop(0)
        
        self.after(100, self._update_ui)
    
    # --- PERBAIKAN V29: Menggunakan _load_settings v21 ---
    def _load_settings(self):
        """Memuat path terakhir dan tanggal cek lisensi dari settings.json."""
        if not os.path.exists(SETTINGS_FILE):
            self._log("File 'settings.json' tidak ditemukan. Melewati.")
            return
        
        try:
            with open(SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
        except Exception as e:
            self._log(f"Gagal memuat 'settings.json': {e}")
            return

        api_path = settings.get("api_file_path")
        output_path = settings.get("output_dir")
        check_date_str = settings.get("last_license_check_date")

        if check_date_str:
            try:
                self.last_license_check_date = date.fromisoformat(check_date_str)
            except ValueError:
                self._log("Format tanggal di settings.json salah, abaikan.")
                self.last_license_check_date = date.min

        if api_path and os.path.exists(api_path):
            self.api_file_path.set(api_path)
            self.api_keys = read_api_keys_from_file(api_path)
            self._log(f"Pengaturan dimuat: File API '{api_path}'")
            self.api_indicator.config(fg=self.colors['success'] if self.api_keys else self.colors['error'])
        
        if output_path and os.path.isdir(output_path):
            self.output_dir.set(output_path)
            self._log(f"Pengaturan dimuat: Folder Output '{output_path}'")
        
        self._update_controls()
    # ----------------------------------------------------

    # --- PERBAIKAN V29: Menggunakan _save_settings v21 ---
    def _save_settings(self):
        """Menyimpan path saat ini dan tanggal cek lisensi ke settings.json."""
        try:
            settings = {
                "api_file_path": self.api_file_path.get(),
                "output_dir": self.output_dir.get(),
                "last_license_check_date": self.last_license_check_date.isoformat()
            }
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(settings, f, indent=4)
            self._log("Pengaturan berhasil disimpan ke 'settings.json'.")
        except Exception as e:
            print(f"Gagal menyimpan pengaturan: {e}")
    # --------------------------------------------------
    
    def _on_closing(self):
        self._save_settings()
        self.destroy()

    # --- PERBAIKAN V29: Menambahkan _remove_key_from_file ---
    def _remove_key_from_file(self, key_to_remove: str):
        file_path = self.api_file_path.get()
        if not file_path or not os.path.exists(file_path):
            return
        try:
            with open(file_path, 'r') as f: lines = f.readlines()
            with open(file_path, 'w') as f:
                for line in lines:
                    if key_to_remove not in line: f.write(line)
            self._log(f"  Kunci {key_to_remove[:4]}*** telah dihapus dari {os.path.basename(file_path)}.")
        except Exception as e:
            self._log(f"  Gagal memperbarui file kunci API: {e}")
    # ----------------------------------------------------

    # --- PERBAIKAN V29: Menambahkan _handle_api_error ---
    def _handle_api_error(self, e: Exception, key: str, operation: str):
        self._log(f"  ERROR: {operation} gagal dengan kunci {key[:4]}***.")
        if isinstance(e, requests.exceptions.HTTPError):
            try:
                error_details = e.response.json()
                self._log(f"  -> Status Code: {e.response.status_code}\n  -> Respon: {error_details}")
                if e.response.status_code == 402 and 'Insufficient credits' in str(error_details):
                    self._log(f"  Kredit untuk kunci {key[:4]}*** telah habis.")
                    if key in self.api_keys: self.api_keys.remove(key)
                    self._remove_key_from_file(key)
            except ValueError:
                self._log(f"  -> Respon tidak dapat di-decode: {e.response.text}")
        else:
            self._log(f"  -> Error: {e}")
    # --------------------------------------------------

    # --- PERBAIKAN V29: Mengganti _process_videos dengan _process_videos_thread ---
    def _process_videos(self):
        videos_to_process = list(self.input_files)
        total = len(videos_to_process)
        self._log(f"Ditemukan {total} video untuk diproses.")
        
        try:
            for idx, video_path in enumerate(videos_to_process, start=1):
                if self.stop_event.is_set(): self._log("Proses dihentikan."); break
                self.pause_event.wait()
                
                self.current_file_label.config(text=f"Processing {idx}/{total}: {os.path.basename(video_path)}")
                self._log(f"Memproses video ({idx}/{total}): {video_path}")
                
                try: 
                    metadata = get_video_metadata(video_path)
                    width, height, fps, frames, duration, size = metadata
                except Exception as e: 
                    self._log(f"Gagal membaca metadata: {e}"); continue

                # Validasi UI
                bitrate = estimate_bitrate(size, duration)
                self._update_quality_check("Resolution", width >= 1920 and height >= 1080)
                self._update_quality_check("Bitrate", bitrate >= 10, f"({bitrate:.1f} Mbps)")
                self._update_quality_check("Duration", ADOBE_MIN_DURATION <= duration <= ADOBE_MAX_DURATION, f"({duration:.1f}s)")
                
                # Dapatkan pengaturan dari UI
                preset = self.adobe_presets[self.preset_var.get()]

                # Tentukan resolusi output dari pilihan user
                res_choice = self.resolution_var.get()
                if res_choice.startswith("4K"):
                    out_width, out_height = 3840, 2160
                elif res_choice.startswith("1080"):
                    out_width, out_height = 1920, 1080
                else:
                    out_width, out_height = width, height
                self._log(f"  Output resolution: {out_width}x{out_height} ({res_choice})")

                # Pilihan FPS user (default ke normalisasi sumber)
                fps_choice = self.fps_var.get()
                if fps_choice == "Original":
                    out_fps = fps  # tidak dinormalisasi, ikut angka asli
                    self._log(f"  Output FPS mengikuti sumber: {out_fps:.3f}")
                else:
                    try:
                        out_fps = float(fps_choice)
                        self._log(f"  Output FPS dipaksa ke {out_fps:.3f}")
                    except ValueError:
                        out_fps = fps
                        self._log(f"  Output FPS input tidak valid, pakai sumber: {out_fps:.3f}")

                # Smart pick: model & unsharp
                selected_model, unsharp_filter = pick_model_and_sharpen(width, height, fps, bitrate)
                selected_models = [selected_model]
                self._log(f"  Smart pick model: {selected_model} | Sharpen: {unsharp_filter}")

                slow_motion_factor = 1.0 # UI ini tidak memiliki Pilihan Slow Mo (tapi logikanya ada)
                
                # --- PERBAIKAN V29: Gunakan variabel mute_var & delete_original_var ---
                mute_audio = self.mute_var.get()
                delete_original = self.delete_original_var.get()
                # -----------------------------------------------------------------

                video_encoder = "H264" # UI ini default ke H.264
                video_profile = "High"
                output_container = "mp4"
                crf_value = preset.get('crf', 12)
                if out_width <= 1920 and out_height <= 1080:
                    crf_value = min(crf_value, 10)
                elif out_width <= 2560 and out_height <= 1440:
                    crf_value = min(crf_value, 11)
                
                key_candidates = list(self.api_keys)
                success = False
                while key_candidates and not success:
                    if self.stop_event.is_set(): break
                    api_key = key_candidates.pop(0)
                    try:
                        self._update_progress("Membuat request...", None)
                        request = create_request(
                            api_key, selected_models, metadata,
                            out_width, out_height, out_fps, mute_audio,
                            video_encoder, preset['compression'], video_profile, output_container
                        )
                        request_id = request['requestId']
                        self._log(f"  Request dibuat (ID: {request_id}) dengan kunci {api_key[:4]}***")
                        
                        accept = accept_request(api_key, request_id)
                        urls = accept.get('urls', accept.get('uploadUrls', []))
                        
                        if not urls:
                            self._log(f"  Kunci {api_key[:4]}*** tidak memberikan URL. Respon: {accept}")
                            continue
                        
                        self._log(f"  Menerima {len(urls)} URL.")
                        etags = upload_video_parts(urls, video_path, self.log_queue, self._update_progress)
                        complete_upload(api_key, request_id, etags)
                        self._log("  Unggah selesai, memproses di server...")
                        
                        self._update_progress("Processing on server...", 0)
                        
                        while not self.stop_event.is_set():
                            self.pause_event.wait()
                            
                            status = get_status(api_key, request_id)
                            state = status.get('state') or status.get('status') or 'waiting'
                            state_lower = state.lower() if isinstance(state, str) else 'waiting'
                            
                            progress_raw = status.get('progress', 0) or 0
                            if isinstance(progress_raw, (int, float)):
                                progress_val = progress_raw if progress_raw > 1 else progress_raw * 100
                            else:
                                progress_val = 0
                            progress_val = max(0, min(progress_val, 100))
                            
                            self._update_progress(f"Processing... ({state})", progress_val)
                            
                            if progress_val >= 100 and state_lower != 'complete':
                                self._log("  Progres 100%, menunggu status final dari Topaz...")
                                time.sleep(10)
                                continue
                            
                            if state_lower == 'complete' or status.get('download'):
                                self._update_progress("Processing selesai. Mengunduh...", 100)
                                download_url = status['download']['url']
                                
                                video_name_base = os.path.splitext(os.path.basename(video_path))[0]
                                temp_file = os.path.join(self.output_dir.get(), f"temp_{video_name_base}.mp4")
                                download_video(download_url, temp_file)
                                
                                self._update_progress("Optimizing for Adobe Stock (FFmpeg)...", None)
                                final_file = os.path.join(self.output_dir.get(), 
                                                          f"AdobeStock_{video_name_base}.mp4")
                                final_file = get_unique_filepath(final_file)

                                original_duration = metadata[4]
                                desired_final_duration = original_duration * slow_motion_factor

                                reencode_success = False
                                try:
                                    if reencode_video_adobe_optimized(
                                        temp_file, final_file,
                                        "libx264",
                                        preset['preset'], crf_value,
                                        video_path, mute_audio, self.log_queue,
                                        target_fps=out_fps,
                                        original_duration=original_duration,
                                        desired_duration=desired_final_duration,
                                        sharp_filter=unsharp_filter
                                    ):
                                        reencode_success = True
                                    else:
                                        self._log("  Re-encode gagal.")
                                finally:
                                    if os.path.exists(temp_file):
                                        os.remove(temp_file)
                                        self._log(f"  File temp '{os.path.basename(temp_file)}' telah dihapus.")

                                if not reencode_success:
                                    break

                                self._log(f"SUKSES: Video '{video_path}' telah di-upscale.")
                                
                                if delete_original:
                                    try: 
                                        os.remove(video_path)
                                        self._log(f"  File asli '{video_path}' telah dihapus (sesuai opsi).")
                                    except OSError as e: 
                                        self._log(f"  Gagal menghapus file asli: {e}")
                                else:
                                    self._log(f"  File asli '{video_path}' tetap disimpan (sesuai opsi).")
                                
                                try:
                                    if api_key in self.api_keys:
                                        self.api_keys.remove(api_key)
                                        self.api_keys.append(api_key)
                                        self._log(f"  Kunci {api_key[:4]}*** sukses, dirotasi ke akhir.")
                                except Exception as e:
                                    self._log(f"  Gagal merotasi kunci API: {e}")
                                
                                # Hapus entry dari queue UI dan sumber data
                                if video_path in self.input_files:
                                    try:
                                        idx_in_list = self.input_files.index(video_path)
                                        self.input_files.pop(idx_in_list)
                                        try:
                                            self.queue_listbox.delete(idx_in_list)
                                        except Exception:
                                            pass
                                        self._update_queue_count()
                                    except ValueError:
                                        pass

                                success = True; break
                            elif state_lower in ('failed', 'cancelled'):
                                self._log(f"  Proses gagal di server: {state}"); break
                            time.sleep(10)
                    
                    except Exception as e:
                        self._handle_api_error(e, api_key, "Siklus proses")
                        continue
                
                if not success:
                    self._log(f"GAGAL: Tidak dapat memproses video '{video_path}'.")
                
                self._update_progress("Ready", 0)
                
            self._log("Semua pekerjaan selesai.")
            
        except Exception as e:
            self._log(f"ERROR KRITIS PADA THREAD: {e}")
            import traceback
            self._log(traceback.format_exc())
            self.status_label.config(text="Terjadi error kritis, periksa log.")
        finally:
            self.is_processing = False
            self._reset_controls()
    # --- AKHIR PERBAIKAN V29 (THREAD) ---

    def _reset_controls(self):
        self.status_label.config(text="Semua Selesai!")
        self.pause_event.set()
        
        self.is_processing = False
        self.pause_btn.text = "PAUSE"
        self.pause_btn.set_enabled(False)
        self.stop_btn.set_enabled(False)
        self._update_controls()


if __name__ == "__main__":
    app = AdobeStockUpscaler()
    app.mainloop()
